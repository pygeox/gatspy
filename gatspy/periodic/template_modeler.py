"""
Implementation of a template modeler for RR Lyrae Stars.

This is based on the algorithm described in Sesar 2010; the same paper is the
source of the templates used here for the fit.
"""
import numpy as np
from scipy.optimize import minimize
from scipy.interpolate import UnivariateSpline

from ..datasets import fetch_rrlyrae_templates
from .modeler import PeriodicModeler, PeriodicModelerMultiband


__all__ = ['RRLyraeTemplateModeler', 'RRLyraeTemplateModelerMultiband']


class RRLyraeTemplateModeler(PeriodicModeler):
    """Template-fitting periods for single-band RR Lyrae

    This class contains functionality to evaluate the fit of the Sesar 2010
    RR Lyrae templates to single-band data.

    Parameters
    ----------
    filts : list or iterable of characters (optional)
        The filters of the templates to be used. Items should be among 'ugriz'.
        Default is 'ugriz'; i.e. all available templates.
    optimizer : PeriodicOptimizer instance (optional)
        Optimizer to use to find the best period. If not specified, the
        LinearScanOptimizer will be used.

    See Also
    --------
    RRLyraeTemplateModelerMultiband : multiband version of template model
    """
    raw_templates = fetch_rrlyrae_templates()

    @classmethod
    def _interpolated_template(cls, template_id):
        """Return an interpolator for the given template"""
        phase, y = cls.raw_templates.get_template(template_id)

        # explicitly add phase=1 to avoid extrapolation
        phase = np.concatenate([phase[-5:] - 1, phase, phase[:5] + 1])
        y = np.concatenate([y[-5:], y, y[:5]])

        return UnivariateSpline(phase, y, s=0, k=5)

    def __init__(self, filts='ugriz', optimizer=None):
        filts = list(filts)
        self.templates = [self._interpolated_template(tmpid)
                          for tmpid in self.raw_templates.ids
                          if tmpid[-1] in filts]
        if len(self.templates) == 0:
            raise ValueError('Filters {0} are not within templates'
                             ''.format(filts))
        PeriodicModeler.__init__(self, optimizer)

    def _fit(self, t, y, dy):
        if dy.size == 1:
            ymean = np.mean(y)
        else:
            w = 1 / dy ** 2
            ymean = np.dot(y, w) / w.sum()
        self.chi2_0_ = np.sum((y - ymean) ** 2 / self.dy ** 2)

    def _score(self, periods):
        scores = np.zeros(periods.shape)

        for i, period in enumerate(periods.flat):
            theta_best, chi2 = self._eval_templates(period)
            scores.flat[i] = 1 - min(chi2) / self.chi2_0_

        return scores

    def _predict(self, t, period):
        theta_best, chi2 = self._eval_templates(period)
        i_best = np.argmin(chi2)
        return self._model(t, theta_best[i_best], period, i_best)

    def _eval_templates(self, period):
        """Evaluate the best template for the given period"""
        theta_best = [self._optimize(period, tmpid)
                      for tmpid, _ in enumerate(self.templates)]
        chi2 = [self._chi2(theta, period, tmpid)
                for tmpid, theta in enumerate(theta_best)]

        return theta_best, chi2

    def _model(self, t, theta, period, tmpid):
        """Compute model at t for the given parameters, period, & template"""
        template = self.templates[tmpid]
        phase = (t / period - theta[2]) % 1
        return theta[0] + theta[1] * template(phase)

    def _chi2(self, theta, period, tmpid, return_gradient=False):
        """
        Compute the chi2 for the given parameters, period, & template

        Optionally return the gradient for faster optimization
        """
        template = self.templates[tmpid]
        phase = (self.t / period - theta[2]) % 1
        model = theta[0] + theta[1] * template(phase)
        chi2 = (((model - self.y) / self.dy) ** 2).sum()

        if return_gradient:
            grad = 2 * (model - self.y) / self.dy ** 2
            gradient = np.array([np.sum(grad),
                                 np.sum(grad * template(phase)),
                                 -np.sum(grad * theta[1]
                                         * template.derivative(1)(phase))])
            return chi2, gradient
        else:
            return chi2

    def _optimize(self, period, tmpid, use_gradient=True):
        """Optimize the model for the given period & template"""
        theta_0 = [self.y.min(), self.y.max() - self.y.min(), 0]
        result = minimize(self._chi2, theta_0, jac=bool(use_gradient),
                          bounds=[(None, None), (0, None), (0, 1)],
                          args=(period, tmpid, use_gradient))
        return result.x


class RRLyraeTemplateModelerMultiband(PeriodicModelerMultiband):
    """Multiband version of RR Lyrae template-fitting modeler

    This class contains functionality to evaluate the fit of the Sesar 2010
    RR Lyrae templates to multiband data.

    Parameters
    ----------
    optimizer : PeriodicOptimizer instance (optional)
        Optimizer to use to find the best period. If not specified, the
        LinearScanOptimizer will be used.

    See Also
    --------
    RRLyraeTemplateModeler : single band version of template model
    """

    def _fit(self, t, y, dy, filts):
        self.models_ = []
        for filt in self.unique_filts_:
            mask = (filts == filt)
            model = RRLyraeTemplateModeler(filts=filt)
            model.fit(t[mask], y[mask], dy[mask])
            self.models_.append(model)
        self.modeldict_ = dict(zip(self.unique_filts_, self.models_))

    def _score(self, periods):
        weights = [model.chi2_0_ for model in self.models_]
        scores = [model.score(periods) for model in self.models_]
        return np.dot(weights, scores) / np.sum(weights)

    def _predict(self, t, filts, period):
        result = np.zeros(t.shape)
        for filt in np.unique(filts):
            mask = (filts == filt)
            result[mask] = self.modeldict_[filt].predict(t[mask], period)
        return result
