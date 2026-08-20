"""Tarife dosyalarini diskten okur ve dogrular.

Tarifeler kodda gomulu degildir; `data/carriers/*.yaml` altinda yasar ve
`reload()` ile surec yeniden baslatilmadan tazelenebilir. Fiyat degistiginde
kod degistirmek zorunda kalmak, bu tur bir motorun en sik goruldugu hatasidir.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from ..domain.enums import CarrierCode
from .schema import Tariff


class TariffLoadError(RuntimeError):
    """Bir tarife dosyasi okunamadi veya dogrulamadan gecemedi."""


def load_tariff_file(path: Path) -> Tariff:
    """Tek bir YAML tarife dosyasini okur ve dogrular."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TariffLoadError(f"{path.name}: dosya okunamadi -- {exc}") from exc

    if not isinstance(raw, dict):
        raise TariffLoadError(
            f"{path.name}: beklenen yapi bir sozluk, bulunan {type(raw).__name__}"
        )

    try:
        return Tariff.model_validate(raw)
    except ValidationError as exc:
        raise TariffLoadError(f"{path.name}: tarife dogrulamasi basarisiz --\n{exc}") from exc


class TariffRepository:
    """Bir dizindeki tum tarifeleri tutar; degisiklikte yeniden yukleyebilir."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._tariffs: dict[CarrierCode, Tariff] = {}
        self.reload()

    def reload(self) -> None:
        """Dizini bastan tarar. Tek bir bozuk dosya tum yuklemeyi durdurur --
        yarim yuklenmis bir tarife seti, sessizce yanlis firma secmekten iyidir."""
        files = sorted(self.directory.glob("*.yaml"))
        if not files:
            raise TariffLoadError(f"{self.directory} altinda tarife dosyasi bulunamadi")

        loaded: dict[CarrierCode, Tariff] = {}
        for path in files:
            tariff = load_tariff_file(path)
            if tariff.carrier in loaded:
                raise TariffLoadError(f"{path.name}: {tariff.carrier} icin ikinci tarife dosyasi")
            loaded[tariff.carrier] = tariff
        self._tariffs = loaded

    def __len__(self) -> int:
        return len(self._tariffs)

    def __iter__(self):
        return iter(self._tariffs.values())

    def __contains__(self, carrier: CarrierCode) -> bool:
        return carrier in self._tariffs

    def get(self, carrier: CarrierCode) -> Tariff:
        try:
            return self._tariffs[carrier]
        except KeyError:
            raise KeyError(f"{carrier} icin yuklu tarife yok") from None

    @property
    def carriers(self) -> tuple[CarrierCode, ...]:
        return tuple(self._tariffs)

    def all(self) -> dict[CarrierCode, Tariff]:
        return dict(self._tariffs)

    def synthetic_carriers(self) -> tuple[CarrierCode, ...]:
        """Sentetik tarifeyle calisan firmalar -- arayuzde rozetlenmesi gerekenler."""
        return tuple(code for code, t in self._tariffs.items() if t.is_synthetic)
