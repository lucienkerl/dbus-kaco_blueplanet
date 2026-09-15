#!/usr/bin/env python
"""Entry point for the Kaco Blueplanet multi-inverter Venus OS driver.

The daemontools service (see service/run) invokes this file directly by its
fixed path, so it stays a thin wrapper - the actual implementation lives in
the importable kaco_*.py modules alongside it (kaco_config, kaco_registers,
kaco_instance, kaco_inverter, kaco_orchestrator).
"""
import os
import sys

sys.path.insert(1, os.path.join(os.path.dirname(__file__), 'ext', 'velib_python'))

from kaco_orchestrator import main

if __name__ == '__main__':
    main()
