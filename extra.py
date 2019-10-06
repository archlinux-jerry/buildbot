#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# extra.py: Automatic management tool for an arch repo.
# This file is part of Buildbot by JerryXiao

import os
import logging

from pathlib import Path
from utils import print_exc_plus

from config import PKGBUILD_DIR, MAIN_LOGFILE, CONSOLE_LOGFILE, \
                   PKG_UPDATE_LOGFILE, MAKEPKG_LOGFILE

import re

ASCII_CRL_REPL = re.compile('\x1B[@-_][0-?]*[ -/]*[@-~]')

logger = logging.getLogger(f'buildbot.{__name__}')

abspath=os.path.abspath(__file__)
abspath=os.path.dirname(abspath)
os.chdir(abspath)

REPO_ROOT = Path(PKGBUILD_DIR)

# generate package list
def gen_pkglist(pkgconfigs, pkgvers, pkgerrs):
    # pkgall contains details
    # namelist is a list of pkgnames
    pkgall = dict()
    for pc in pkgconfigs:
        ps = ('type', 'cleanbuild', 'timeout', 'priority')
        hps = ('prebuild', 'postbuild', 'update', 'failure')
        dps = {p:getattr(pc, p, None) for p in ps}
        dhps = {p:'\n'.join([str(cmd) for cmd in getattr(pc, p, None)]) for p in hps}
        # additional package details
        ves = {'version': pkgvers.get(pc.dirname, None), 'errors': pkgerrs.get(pc.dirname, None)}
        pkgall[pc.dirname] = {**dps, **dhps, **ves}
    namelist = [k for k in pkgall]
    return (namelist, pkgall)

def __simpleread(fpath, limit=4096-100, dosub=False):
    with open(fpath, 'r') as f:
        c = f.read()
    if dosub:
        c = ASCII_CRL_REPL.sub('', c[-2*limit:])
    if len(c) > limit:
        c = c[-limit:]
    return c
# read logs
def readpkglog(pkgdirname, update=False):
    cwd = REPO_ROOT / pkgdirname
    logfile = PKG_UPDATE_LOGFILE if update else MAKEPKG_LOGFILE
    if cwd.exists() and (cwd / logfile).exists():
        logger.debug(f'formatting {"update" if update else "build"} logs in {pkgdirname}')
        return __simpleread(cwd / logfile, dosub=True)
    else:
        logger.debug(f'not found: {"update" if update else "build"} log in dir {pkgdirname}')
        return f"{cwd / logfile} cannot be found"
def readmainlog(debug=False):
    logfile = MAIN_LOGFILE if debug else CONSOLE_LOGFILE
    if (Path('.') / logfile).exists():
        logger.debug(f'formatting buildbot{" debug" if debug else ""} logs')
        return __simpleread(Path('.') / logfile)
    else:
        logger.debug(f'not found: buildbot{" debug" if debug else ""} log')
        return f"{Path('.') / logfile} cannot be found"
