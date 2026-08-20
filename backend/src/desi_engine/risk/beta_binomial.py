"""Beta-Binom makinesi: posterior ve konsantrasyon parametresi kestirimi.

Neden Beta-Binom?
    Hasar bir Bernoulli olayidir (gonderi hasarli/saglam). Bir hucredeki gercek
    oran `p` bilinmiyor; onu bir Beta dagilimiyla temsil ediyoruz. Beta,
    Binom'un eslenik onselidir, bu yuzden posterior yine bir Beta olur ve
    kapali formda yazilir -- MCMC'ye gerek kalmaz. 50 bin siparislik bir Monte
    Carlo kosusunda bu, saniyelerle saatler arasindaki farktir.

Kritik parametre: konsantrasyon `kappa`
    `alpha = kappa * p_onsel`, `beta = kappa * (1 - p_onsel)` yazdigimizda
    posterior ortalama tam olarak sunu verir:

        p_posterior = (kappa * p_onsel + gozlenen_hasar) / (kappa + gonderi_sayisi)

    Yani `kappa`, onselin **kac gonderilik veriye denk** sayildigidir. `kappa`
    elle secilmez -- verinin kendisinden, marjinal olabilirlik maksimize edilerek
    kestirilir. Hucreler arasi gercek farklilik buyukse kucuk bir `kappa` cikar
    (veriye guven), farklilik gurultuden ibaretse buyuk bir `kappa` cikar
    (onsele guven).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
from scipy.special import betaln
from scipy.stats import beta as beta_dist

#: `kappa` icin arama izgarasi. Ust sinir kasitli olarak sonlu: sonsuz `kappa`,
#: 9000 gonderilik bir hucreyi bile onsele ezdirirdi.
KAPPA_GRID: Final[np.ndarray] = np.logspace(0.0, 4.0, 90)

#: Hicbir hucrede olay yoksa marjinal olabilirlik `kappa`'da duzlesir. O durumda
#: "veri hucreler arasi fark gostermiyor, onsele yaslan" demek dogru davranis.
DEFAULT_KAPPA: Final[float] = float(KAPPA_GRID[-1])


@dataclass(frozen=True, slots=True)
class BetaPosterior:
    """Bir hucrenin hasar orani icin posterior dagilim."""

    alpha: float
    beta: float
    observations: int
    events: int
    prior_mean: float
    kappa: float

    @property
    def mean(self) -> float:
        """Posterior ortalama -- motorun kullandigi nokta tahmini."""
        return self.alpha / (self.alpha + self.beta)

    @property
    def raw_rate(self) -> float:
        """Shrinkage uygulanmamis ham oran. Yalnizca karsilastirma icin.

        Seyrek hucrelerde bu sayi ya 0.0000 ("risksiz") ya da 1/33 gibi absurt
        yuksek cikar; ikisi de karar vermek icin kullanilamaz.
        """
        return self.events / self.observations if self.observations else float("nan")

    @property
    def shrinkage_weight(self) -> float:
        """Tahminin ne kadarinin onselden geldigi (0 = tamamen veri, 1 = tamamen onsel).

        Arayuzde belirsizligi gostermenin en anlasilir yolu bu: "%92 onselden"
        demek, "bu hucre hakkinda neredeyse hicbir sey bilmiyoruz" demektir.
        """
        return self.kappa / (self.kappa + self.observations)

    @property
    def variance(self) -> float:
        total = self.alpha + self.beta
        return (self.alpha * self.beta) / (total**2 * (total + 1))

    def credible_interval(self, level: float = 0.90) -> tuple[float, float]:
        """Esit kuyruklu guvenilir aralik."""
        tail = (1.0 - level) / 2.0
        return (
            float(beta_dist.ppf(tail, self.alpha, self.beta)),
            float(beta_dist.ppf(1.0 - tail, self.alpha, self.beta)),
        )

    def upper_bound(self, level: float = 0.95) -> float:
        """Posterior ust guven siniri.

        Riskten kacinan modda nokta tahmin yerine bu kullanilir: "bu firma hakkinda
        az sey biliyoruz" durumu, otomatik olarak daha yuksek bir risk varsayimina
        donusur ve az veriye sahip firma kayirilmis olmaz.
        """
        return float(beta_dist.ppf(level, self.alpha, self.beta))


def beta_binomial_loglik(
    n: np.ndarray, d: np.ndarray, alpha: np.ndarray, beta: np.ndarray
) -> float:
    """Beta-Binom marjinal log-olabilirligi (kombinasyon terimi haric).

    Kombinasyon terimi `log C(n, d)` `alpha`/`beta`'dan bagimsiz oldugu icin
    maksimizasyonda atlanabilir.
    """
    return float(np.sum(betaln(d + alpha, n - d + beta) - betaln(alpha, beta)))


def fit_concentration(
    observations: np.ndarray,
    events: np.ndarray,
    prior_means: np.ndarray,
    grid: np.ndarray | None = None,
) -> float:
    """`kappa`'yi marjinal olabilirligi maksimize ederek kestirir.

    Her hucrenin kendi onsel ortalamasi olabilir (hiyerarsinin alt katmanlarinda
    onsel, ust katmanin o hucre icin urettigi tahmindir). Izgara aramasi
    kullaniliyor -- 90 nokta, deterministik, turev gerektirmez ve yerel
    maksimuma takilmaz. Optimizasyon suresi burada onemsiz cunku `fit` yalnizca
    bir kez calisir.
    """
    grid = KAPPA_GRID if grid is None else grid

    usable = observations > 0
    if not np.any(usable):
        return DEFAULT_KAPPA

    n = observations[usable].astype(float)
    d = events[usable].astype(float)
    p = np.clip(prior_means[usable], 1e-6, 1 - 1e-6)

    best_kappa = DEFAULT_KAPPA
    best_loglik = -np.inf
    for kappa in grid:
        loglik = beta_binomial_loglik(n, d, kappa * p, kappa * (1.0 - p))
        if loglik > best_loglik:
            best_loglik, best_kappa = loglik, float(kappa)

    return best_kappa


def posterior(observations: int, events: int, prior_mean: float, kappa: float) -> BetaPosterior:
    """Bir hucrenin posteriorunu kurar.

    `alpha = kappa * p_onsel + gozlenen_hasar`
    `beta  = kappa * (1 - p_onsel) + gozlenen_saglam`
    """
    prior_mean = float(np.clip(prior_mean, 1e-9, 1 - 1e-9))
    return BetaPosterior(
        alpha=kappa * prior_mean + events,
        beta=kappa * (1.0 - prior_mean) + (observations - events),
        observations=observations,
        events=events,
        prior_mean=prior_mean,
        kappa=kappa,
    )
