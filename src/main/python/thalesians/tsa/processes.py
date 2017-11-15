import datetime as dt

import numpy as np
import scipy.linalg as la

import thalesians.tsa.checks as checks
import thalesians.tsa.distrs as distrs
import thalesians.tsa.numpyutils as npu
import thalesians.tsa.numpychecks as npc

class Process(object):
    def __init__(self, **kwargs):
        try:
            super(Process, self).__init__(**kwargs)
        except TypeError:
            super(Process, self).__init__()

class ItoProcess(Process):
    def __init__(self, process_dim=1, noise_dim=None, drift=None, diffusion=None, **kwargs):
        self._process_dim = process_dim
        self._noise_dim = process_dim if noise_dim is None else noise_dim
        # Note: the brackets around the lambdas below are essential, otherwise the result of the parsing will not be what we need:
        self._drift = (lambda t, x: npu.row_of(self._process_dim, 0.)) if drift is None else drift
        self._diffusion = (lambda t, x: npu.matrix_of(self._process_dim, self._noise_dim, 0.)) if diffusion is None else diffusion
        super(ItoProcess, self).__init__(process_dim=self._process_dim, noise_dim=self._noise_dim, drift=self._drift, diffusion=self._diffusion, **kwargs)
        
    @property
    def process_dim(self):
        return self._process_dim
    
    @property
    def noise_dim(self):
        return self._noise_dim
    
    @property
    def drift(self):
        return self._drift
    
    @property
    def diffusion(self):
        return self._diffusion
    
    def __str__(self):
        return 'ItoProcess(process_dim=%d, noise_dim=%d)' % (self._process_dim, self._noise_dim)
    
class SolvedItoProcess(ItoProcess):
    def __init__(self, process_dim=1, noise_dim=None, drift=None, diffusion=None, **kwargs):
        super(SolvedItoProcess, self).__init__(process_dim=process_dim, noise_dim=noise_dim, drift=drift, diffusion=diffusion, **kwargs)
        
    def propagate(self, time, variate, time0, value0, state0=None):
        raise NotImplementedError()
    
    def __str__(self):
        return 'SolvedItoProcess(process_dim=%d, noise_dim=%d)' % (self.process_dim, self.noise_dim)

class MarkovProcess(Process):
    def __init__(self, process_dim, time_unit=dt.timedelta(days=1), **kwargs):
        self._process_dim = checks.check_int(process_dim)
        self._time_unit = time_unit
        
        self._cached_time = None
        self._cached_time0 = None
        self._cached_distr0 = None
        self._cached_distr = None
        super(MarkovProcess, self).__init__(process_dim=process_dim, **kwargs)
        
    def propagate_distr(self, time, time0, distr0):
        if time == time0: return distr0
        if self._cached_time is None or self._cached_time != time or self._cached_time0 != time0 or self._cached_distr0 != distr0:
            time_delta = time - time0
            if isinstance(time_delta, dt.timedelta):
                time_delta = time_delta.total_seconds() / self._time_unit.total_seconds()
            self._cached_distr = self._propagate_distr_impl(time_delta, distr0)
            self._cached_time = time
            self._cached_time0 = time0
            self._cached_distr0 = distr0
        return self._cached_distr
    
    def _propagate_distr_impl(self, time_delta, distr0):
        raise NotImplementedError()
    
    def __str__(self):
        return 'MarkovProcess(process_dim=%d)' % self._process_dim
    
class SolvedItoMarkovProcess(MarkovProcess, SolvedItoProcess):
    def __init__(self, process_dim=1, noise_dim=None, drift=None, diffusion=None, **kwargs):
        super(SolvedItoMarkovProcess, self).__init__(process_dim=process_dim, noise_dim=noise_dim, drift=drift, diffusion=diffusion, **kwargs)
    
    def propagate(self, time, variate, time0, value0, state0=None):
        if self.noise_dim != self.process_dim:
            raise NotImplementedError('Cannot utilise the propagate_distr of the Markov process in propagate if noise_dim != process_dim; provide a custom implementation')
        if time == time0: return npu.to_ndim_2(value0, ndim_1_to_col=True, copy=True)
        value0 = npu.to_ndim_2(value0, ndim_1_to_col=True, copy=False)
        variate = npu.to_ndim_2(variate, ndim_1_to_col=True, copy=False)
        distr = self.propagate_distr(time, time0, distrs.NormalDistr.create_dirac_delta(value0))
        return distr.mean + np.dot(np.linalg.cholesky(distr.cov), variate)

    def __str__(self):
        return 'SolvedItoMarkovProcess(process_dim=%d, noise_dim=%d)' % (self.process_dim, self.noise_dim)

# TODO To be implemented
class KalmanProcess(MarkovProcess):
    def __init__(self):
        pass
    
class WienerProcess(SolvedItoMarkovProcess):
    def __init__(self, mean=None, vol=None):
        if mean is None and vol is None:
            mean = 0.; vol = 1.
        
        self._mean, self._vol = None, None
        
        if mean is not None:
            self._mean = npu.to_ndim_2(mean, ndim_1_to_col=True, copy=True)
            process_dim = npu.nrow(self._mean)
        if vol is not None:
            self._vol = npu.to_ndim_2(vol, ndim_1_to_col=True, copy=True)
            process_dim = npu.nrow(self._vol)
        
        if self._mean is None: self._mean = npu.col_of(process_dim, 0.)
        if self._vol is None: self._vol = np.eye(process_dim)
        
        npc.check_col(self._mean)
        npc.check_nrow(self._mean, process_dim)
        npc.check_nrow(self._vol, process_dim)
        
        noise_dim = npu.ncol(self._vol)
        self._cov = np.dot(self._vol, self._vol.T)
        
        npu.make_immutable(self._mean)
        npu.make_immutable(self._vol)
        npu.make_immutable(self._cov)
        
        super(WienerProcess, self).__init__(process_dim=process_dim, noise_dim=noise_dim, drift=lambda t, x: self._mean, diffusion=lambda t, x: self._vol)
        
    @staticmethod
    def create_2d(mean1, mean2, sd1, sd2, cor):
        return WienerProcess(npu.col(mean1, mean2), distrs.NormalDistr.make_vol_2d(sd1, sd2, cor))
    
    @staticmethod
    def create_from_cov(mean, cov):
        return WienerProcess(mean, distrs.NormalDistr.make_vol_from_cov(cov))
    
    @property
    def mean(self):
        return self._mean
    
    @property
    def vol(self):
        return self._vol
    
    @property
    def cov(self):
        return self._cov
    
    def propagate(self, time, variate, time0, value0, state0=None):
        if time == time0: return npu.to_ndim_2(value0, ndim_1_to_col=True, copy=True)
        value0 = npu.to_ndim_2(value0, ndim_1_to_col=True, copy=False)
        variate = npu.to_ndim_2(variate, ndim_1_to_col=True, copy=False)
        time_delta = time - time0
        return value0 + self._mean * time_delta + np.dot(self._vol, np.sqrt(time_delta) * variate)
    
    def _propagate_distr_impl(self, time_delta, distr0):
        mean = distr0.mean + self._mean * time_delta
        cov = distr0.cov + time_delta * self._cov
        return distrs.NormalDistr(mean=mean, cov=cov)
        
    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self._mean == other._mean and self._vol == other._vol
        return False
    
    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return 'WienerProcess(process_dim=%d, noise_dim=%d, mean=%s, vol=%s)' % (self.process_dim, self.noise_dim, str(self._mean), str(self._vol))

class OrnsteinUhlenbeckProcess(SolvedItoMarkovProcess):
    def __init__(self, transition=None, mean=None, vol=None):
        if transition is None and mean is None and vol is None:
            transition = 1.; mean = 0.; vol = 1.
            
        self._transition, self._mean, self._vol = None, None, None
            
        if transition is not None:
            self._transition = npu.to_ndim_2(transition, ndim_1_to_col=True, copy=True)
            process_dim = npu.nrow(self._transition)
        if mean is not None:
            self._mean = npu.to_ndim_2(mean, ndim_1_to_col=True, copy=True)
            process_dim = npu.nrow(self._mean)
        if vol is not None:
            self._vol = npu.to_ndim_2(vol, ndim_1_to_col=True, copy=True)
            process_dim = npu.nrow(self._vol)
        
        if self._transition is None: self._transition = np.eye(process_dim)
        if self._mean is None: self._mean = npu.col_of(process_dim, 0.)
        if self._vol is None: self._vol = np.eye(process_dim)
        
        npc.check_square(self._transition)
        npc.check_nrow(self._transition, process_dim)
        npc.check_col(self._mean)
        npc.check_nrow(self._mean, process_dim)
        npc.check_nrow(self._vol, process_dim)
        
        noise_dim = npu.ncol(self._vol)
        
        self._transition_x_2 = npu.kron_sum(self._transition, self._transition)
        self._transition_x_2_inverse = np.linalg.inv(self._transition_x_2)
        self._cov = np.dot(self._vol, self._vol.T)
        self._cov_vec = npu.vec(self._cov)
        
        self._cached_mean_reversion_factor = None
        self._cached_mean_reversion_factor_time_delta = None
        self._cached_mean_reversion_factor_squared = None
        self._cached_mean_reversion_factor_squared_time_delta = None
        
        npu.make_immutable(self._transition)
        npu.make_immutable(self._transition_x_2)
        npu.make_immutable(self._transition_x_2_inverse)
        npu.make_immutable(self._mean)
        npu.make_immutable(self._vol)
        npu.make_immutable(self._cov)
        npu.make_immutable(self._cov_vec)
        
        super(OrnsteinUhlenbeckProcess, self).__init__(process_dim=process_dim, noise_dim=noise_dim, drift=lambda t, x: -np.dot(self._transition, x - self._mean), diffusion=lambda t, x: self._vol)
        
    @property
    def transition(self):
        return self._transition
        
    @property
    def mean(self):
        return self._mean
    
    @property
    def vol(self):
        return self._vol
    
    def mean_reversion_factor(self, time_delta):
        if self._cached_mean_reversion_factor_time_delta is None or self._cached_mean_reversion_factor_time_delta != time_delta:
            self._cached_mean_reversion_factor_time_delta = time_delta
            self._cached_mean_reversion_factor = la.expm(self._transition * (-time_delta))
        return self._cached_mean_reversion_factor
    
    def mean_reversion_factor_squared(self, time_delta):
        if self._cached_mean_reversion_factor_squared_time_delta is None or self._cached_mean_reversion_factor_squared_time_delta != time_delta:
            self._cached_mean_reversion_factor_squared_time_delta = time_delta
            self._cached_mean_reversion_factor_squared = la.expm(self._transition_x_2 * (-time_delta))
        return self._cached_mean_reversion_factor_squared
        
    def noise_covariance(self, time_delta):
        mrfsquared = self.mean_reversion_factor_squared(time_delta)
        eyeminusmrfsquared = np.eye(self.process_dim) - mrfsquared
        return npu.unvec(np.dot(np.dot(self._transition_x_2_inverse, eyeminusmrfsquared), self._cov_vec), self.process_dim)
        
    def propagate(self, time, variate, time0, value0, state0=None):
        if time == time0: return npu.to_ndim_2(value0, ndim_1_to_col=True, copy=True)
        value0 = npu.to_ndim_2(value0, ndim_1_to_col=True, copy=False)
        variate = npu.to_ndim_2(variate, ndim_1_to_col=True, copy=False)
        time_delta = time - time0
        mrf = self.mean_reversion_factor(time_delta)
        eyeminusmrf = np.eye(self.process_dim) - mrf
        m = np.dot(mrf, value0) + np.dot(eyeminusmrf, self._mean)
        c = self.noise_covariance(time_delta)
        return m + np.dot(np.linalg.cholesky(c), variate)
        
    def _propagate_distr_impl(self, time_delta, distr0):
        value0 = distr0.mean
        mrf = self.mean_reversion_factor(time_delta)
        eyeminusmrf = np.eye(self.process_dim) - mrf
        m = np.dot(mrf, value0) + np.dot(eyeminusmrf, self._mean)
        c = np.dot(np.dot(mrf, distr0.cov), mrf.T) + self.noise_covariance(time_delta)
        return distrs.NormalDistr(mean=m, cov=c)
    
    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self._mean == other._mean and self._vol == other._vol
        return False
    
    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return 'OrnsteinUhlenbeckProcess(process_dim=%d, noise_dim=%d, transition=%s, mean=%s, vol=%s)' % (self.process_dim, self.noise_dim, str(self._transition), str(self._mean), str(self._vol))
    