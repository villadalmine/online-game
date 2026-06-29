#!/usr/bin/env python3
"""Mini-simulador determinista de balance para SDD 49 (misiles) y 50 (drones).

Imprime tablas de costo-eficiencia e intercepción/supervivencia derivadas 100% del contenido
(`content/*.yaml`) y de las funciones puras (`simulate_strike`, `simulate_drones`). Sirve para
afinar los números por YAML sin adivinar: ves de un vistazo si un tier domina, cuántas torretas
hacen falta para frenar cada misil, y cuánto dura un escuadrón de drones.

Uso:  python scripts/balance.py     (o: make balance)
Los invariantes de diseño que esto vigila están en tests/test_balance.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.content.registry import get_content  # noqa: E402
from app.services.drones import simulate_drones  # noqa: E402
from app.services.strike import simulate_strike  # noqa: E402

RACE = "terran"


def _role_total(cost: dict) -> int:
    return int(sum(cost.values()))


def missiles_report() -> None:
    c = get_content()
    ip = c.buildings.get("turret", {}).get("intercept_power", 10)
    print(f"\n=== MISILES (SDD 49) — torreta intercept_power={ip} ===")
    print(f"{'misil':16} {'power':>5} {'roles':>5} {'⚡':>3} {'casa':>4} "
          f"{'d/role':>6} {'d/⚡':>5} {'d/casa':>6} {'ic':>3} {'/torreta':>8} {'torretas→1':>10}")
    for key in ("sonic_missile", "cruise_missile", "nuclear_missile"):
        u = c.units[key]
        power = u["power"]
        roles = _role_total(u.get("cost", {}))
        e = u.get("energy_cost", 1)
        house = u.get("housing_size", 1)
        ic = u.get("intercept_cost", 1)
        per_turret = ip / ic                      # cuántos frena 1 torreta
        turrets_to_stop_one = ic / ip             # torretas para frenar 1
        print(f"{key:16} {power:>5} {roles:>5} {e:>3} {house:>4} "
              f"{power/roles:>6.2f} {power/e:>5.1f} {power/house:>6.1f} {ic:>3} "
              f"{per_turret:>8.2f} {turrets_to_stop_one:>10.2f}")
    # escenarios
    print("\n  escenarios (capacidad = nº torretas × intercept_power):")
    for force, cap in (({"sonic_missile": 40}, 3 * ip), ({"nuclear_missile": 1}, 2 * ip),
                       ({"nuclear_missile": 1}, 3 * ip)):
        r = simulate_strike(force, cap)
        print(f"    {force} vs {cap // ip} torretas → impactan {r.impacted}, "
              f"interceptan {r.intercepted}, daño {r.damage:.0f}")


def drones_report() -> None:
    c = get_content()
    aa = c.buildings.get("turret", {}).get("antiair_power", 30)
    print(f"\n=== DRONES (SDD 50) — torreta antiair_power={aa} ===")
    print(f"{'dron':18} {'hp':>4} {'drain':>5} {'intel':>5} {'atk':>4} {'roles':>5} "
          f"{'hp/drain':>8} {'ticks@1t':>8} {'ticks@3t':>8}")
    for key in ("recon_drone", "recon_drone_mk2", "recon_drone_mk3", "strike_drone"):
        u = c.units[key]
        hp = u.get("hp", 1)
        drain = u.get("energy_per_tick", 0)
        iq = u.get("intel_quality", 0)
        atk = u.get("attack", 0)
        roles = _role_total(u.get("cost", {}))
        # supervivencia de 4 drones vs 1 / 3 torretas, energía infinita (aísla las torretas)
        s1 = simulate_drones({key: 4}, aa * 1, 1e9, 1e9)
        s3 = simulate_drones({key: 4}, aa * 3, 1e9, 1e9)
        print(f"{key:18} {hp:>4} {drain:>5.1f} {iq:>5.2f} {atk:>4} {roles:>5} "
              f"{hp/max(drain,0.01):>8.1f} {s1.survive_ticks:>8} {s3.survive_ticks:>8}")
    print("\n  duración por energía (5×mk3, drain 20/tick, regen 0):")
    for energy in (40, 100, 1000):
        s = simulate_drones({"recon_drone_mk3": 5}, 0, energy, 0)
        print(f"    energía {energy:>5} → {s.survive_ticks} ticks "
              f"(muere por energía: {s.died_of_energy})")


def roles_report() -> None:
    """SDD 53: cómo se reparte el costo por rol y a qué mineral cae en cada raza. Sirve para ver de
    un vistazo que ningún rol gatea todo y que la defensa (turret/soldier) cae SOLO en
    structural."""
    c = get_content()
    races = ["terran", "martian", "venusian"]
    print("\n=== ROLES POR ITEM (SDD 53) — reparto structural/energetic/advanced ===")
    print("mapeo rol→mineral por raza:")
    for r in races:
        rr = c.races[r]["resource_roles"]
        print(f"  {r:9} struct={rr['structural']:9} energetic={rr['energetic']:9} "
              f"advanced={rr['advanced']}")
    items = ([(k, c.buildings[k].get("cost", {}), "edif") for k in c.buildings]
             + [(k, c.units[k].get("cost", {}), "unid") for k in c.units])
    print(f"\n{'item':18} {'tipo':5} {'struct':>6} {'energ':>6} {'adv':>5}  reparto")
    for key, cost, kind in items:
        st, en, ad = cost.get("structural", 0), cost.get("energetic", 0), cost.get("advanced", 0)
        tot = st + en + ad or 1
        bar = f"S{int(100*st/tot):>3}% E{int(100*en/tot):>3}% A{int(100*ad/tot):>3}%"
        print(f"{key:18} {kind:5} {st:>6} {en:>6} {ad:>5}  {bar}")
    # invariante visible: defensa básica = SOLO structural
    print("\n  anti-lockout (defensa con SOLO el mineral structural por raza):")
    for r in races:
        t = c.building_cost_in_minerals(r, "turret")
        s = c.unit_cost_in_minerals(r, "soldier")
        print(f"    {r:9} turret={t} soldier={s}")


def main() -> int:
    missiles_report()
    drones_report()
    roles_report()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
