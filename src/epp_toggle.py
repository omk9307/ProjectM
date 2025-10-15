import argparse
import ctypes
import json
import os
import sys
from typing import Dict, Tuple

try:
    import winreg  # type: ignore
except Exception:  # pragma: no cover
    winreg = None


# WinAPI constants
SPI_GETMOUSE = 0x0003
SPI_SETMOUSE = 0x0004
SPI_GETMOUSESPEED = 0x0070
SPI_SETMOUSESPEED = 0x0071
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02

user32 = ctypes.windll.user32


def spi_get_mouse() -> Tuple[int, int, int]:
    arr = (ctypes.c_int * 3)()
    if not user32.SystemParametersInfoW(SPI_GETMOUSE, 0, ctypes.byref(arr), 0):
        raise OSError("SPI_GETMOUSE failed")
    return int(arr[0]), int(arr[1]), int(arr[2])


def spi_set_mouse(th1: int, th2: int, accel: int) -> None:
    arr = (ctypes.c_int * 3)(int(th1), int(th2), int(accel))
    if not user32.SystemParametersInfoW(
        SPI_SETMOUSE, 0, ctypes.byref(arr), SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
    ):
        raise OSError("SPI_SETMOUSE failed")


def spi_get_speed() -> int:
    spd = ctypes.c_uint(0)
    if not user32.SystemParametersInfoW(SPI_GETMOUSESPEED, 0, ctypes.byref(spd), 0):
        raise OSError("SPI_GETMOUSESPEED failed")
    return int(spd.value)


def spi_set_speed(speed: int) -> None:
    val = ctypes.c_uint(int(speed))
    if not user32.SystemParametersInfoW(
        SPI_SETMOUSESPEED, 0, val, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
    ):
        raise OSError("SPI_SETMOUSESPEED failed")


def reg_read_mouse() -> Dict[str, str]:
    out: Dict[str, str] = {"MouseSpeed": "", "MouseThreshold1": "", "MouseThreshold2": ""}
    if winreg is None:
        return out
    key_path = r"Control Panel\Mouse"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as k:
        for name in ("MouseSpeed", "MouseThreshold1", "MouseThreshold2"):
            try:
                val, _ = winreg.QueryValueEx(k, name)
                out[name] = str(val)
            except FileNotFoundError:
                out[name] = ""
    return out


def reg_write_mouse(values: Dict[str, str]) -> None:
    if winreg is None:
        return
    key_path = r"Control Panel\Mouse"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as k:
        for name, val in values.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, str(val))


def backup_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "mouse_epp_backup.json")


def load_backup() -> Dict[str, str]:
    path = backup_path()
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_backup(data: Dict[str, str]) -> None:
    path = backup_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_epp_off(reg: Dict[str, str], spi_vals: Tuple[int, int, int]) -> bool:
    th1, th2, accel = spi_vals
    # OFF 기준: thresholds == 0,0,0 혹은 레지스트리 0/0/0
    reg_off = (
        reg.get("MouseSpeed", "") == "0"
        and reg.get("MouseThreshold1", "") == "0"
        and reg.get("MouseThreshold2", "") == "0"
    )
    spi_off = (th1 == 0 and th2 == 0 and accel == 0)
    return reg_off or spi_off


def cmd_status() -> int:
    reg = reg_read_mouse()
    th1, th2, accel = spi_get_mouse()
    speed = spi_get_speed()
    off = is_epp_off(reg, (th1, th2, accel))
    print("[STATUS]")
    print(f"  Registry: MouseSpeed={reg.get('MouseSpeed')}, T1={reg.get('MouseThreshold1')}, T2={reg.get('MouseThreshold2')}")
    print(f"  SPI: thresholds=({th1},{th2}), accel={accel}, speed={speed}")
    print(f"  EPP: {'OFF' if off else 'ON'}")
    return 0


def cmd_off() -> int:
    reg = reg_read_mouse()
    th1, th2, accel = spi_get_mouse()
    speed = spi_get_speed()
    save_backup({
        "MouseSpeed": reg.get("MouseSpeed", ""),
        "MouseThreshold1": reg.get("MouseThreshold1", ""),
        "MouseThreshold2": reg.get("MouseThreshold2", ""),
        "SPI_th1": str(th1),
        "SPI_th2": str(th2),
        "SPI_accel": str(accel),
        "SPI_speed": str(speed),
    })
    print(f"[BACKUP] saved to {backup_path()}")

    # Set OFF via SPI first (신뢰도 높음), 레지스트리도 동기화
    spi_set_mouse(0, 0, 0)
    reg_write_mouse({"MouseSpeed": "0", "MouseThreshold1": "0", "MouseThreshold2": "0"})
    print("[APPLY] EPP OFF (thresholds 0,0,0)")

    # 재확인 출력
    return cmd_status()


def cmd_restore() -> int:
    data = load_backup()
    if not data:
        print("[RESTORE] no backup found; nothing to do")
        return 0
    # Restore SPI thresholds/accel and speed
    th1 = int(data.get("SPI_th1", "6") or 6)
    th2 = int(data.get("SPI_th2", "10") or 10)
    accel = int(data.get("SPI_accel", "1") or 1)
    speed = int(data.get("SPI_speed", str(spi_get_speed())))
    spi_set_mouse(th1, th2, accel)
    try:
        spi_set_speed(speed)
    except Exception:
        pass
    # Restore registry snapshot
    reg_vals = {
        "MouseSpeed": data.get("MouseSpeed", "1"),
        "MouseThreshold1": data.get("MouseThreshold1", "6"),
        "MouseThreshold2": data.get("MouseThreshold2", "10"),
    }
    reg_write_mouse(reg_vals)
    print("[APPLY] restored from backup")
    return cmd_status()


def main() -> int:
    parser = argparse.ArgumentParser(description="Toggle Windows Enhance Pointer Precision (EPP)")
    parser.add_argument("action", nargs="?", choices=["status", "off", "restore"], default="status")
    args = parser.parse_args()

    try:
        if args.action == "status":
            return cmd_status()
        if args.action == "off":
            return cmd_off()
        if args.action == "restore":
            return cmd_restore()
    except Exception as e:
        print(f"[ERROR] {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

