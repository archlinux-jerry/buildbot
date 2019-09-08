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
        ps = ('type', 'cleanbuild', 'timeout')
        hps = ('prebuild', 'postbuild', 'update', 'failure')
        dps = {p:getattr(pc, p, None) for p in ps}
        dhps = {p:'\n'.join(str(getattr(pc, p, None))) for p in hps}
        # additional package details
        ves = {'version': pkgvers.get(pc.dirname, None), 'errors': pkgerrs.get(pc.dirname, None)}
        pkgall[pc.dirname] = {**dps, **dhps, **ves}
    namelist = [k for k in pkgall]
    return (namelist, pkgall)

def __simpleread(fpath, limit=4096-100):
    with open(fpath, 'r') as f:
        c = f.read()
    if len(c) > limit:
        c = c[-limit:]
    return c
# read logs
def readpkglog(pkgdirname, update=False):
    cwd = REPO_ROOT / pkgdirname
    logfile = PKG_UPDATE_LOGFILE if update else MAKEPKG_LOGFILE
    if cwd.exists() and (cwd / logfile).exists():
        logger.debug(f'formatting {"update" if update else "build"} logs in {pkgdirname}')
        return __simpleread(cwd / logfile)
    else:
        logger.debug(f'not found: {"update" if update else "build"} log in dir {pkgdirname}')
        return f"{cwd / logfile} cannot be found"
def readmainlog(debug=False):
    logfile = MAIN_LOGFILE if debug else CONSOLE_LOGFILE
    if (PKGBUILD_DIR / logfile).exists():
        logger.debug(f'formatting buildbot{" debug" if debug else ""} logs')
        return __simpleread(PKGBUILD_DIR / logfile)
    else:
        logger.debug(f'not found: buildbot{" debug" if debug else ""} log')
        return f"{PKGBUILD_DIR / logfile} cannot be found"
