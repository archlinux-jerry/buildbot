#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# repo.py: Automatic management tool for an arch repo.
# This file is part of Buildbot by JerryXiao

# Directory structure of the repo:
# buildbot                             -- buildbot (git)
# buildbot/repo                        -- repo root
    # /updates/                        -- new packages goes in here
    # /updates/archive                 -- archive dir, old packages goes in here
    # /www/                            -- http server root
    # /www/archive => /updates/archive -- archive dir for users
    # /www/aarch64                     -- packages for "aarch64"
    # /www/any                         -- packages for "any"
    # /www/armv7h                      -- packages for "armv7h" (No build bot)
    # /www/x86_64                      -- packages for "x86_64"
    # /www/robots.txt => /r_r_n/r.txt  -- robots.txt

import os
from pathlib import Path
import logging
from utils import bash, Pkg, get_pkg_details_from_name
from time import time

from config import REPO_NAME, PKG_COMPRESSION, ARCHS, REPO_CMD

abspath = os.path.abspath(__file__)
repocwd = Path(abspath).parent / 'repo'
repocwd.mkdir(mode=0o755, exist_ok=True)
os.chdir(repocwd)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def symlink(dst, src, exist_ok=True):
    assert issubclass(type(dst), os.PathLike) and type(src) is str
    try:
        dst.symlink_to(src)
    except FileExistsError:
        if not exist_ok:
            raise

def checkenv():
    (Path(abspath).parent / 'recycled').mkdir(mode=0o755, exist_ok=True)
    dirs = [Path('updates/archive')] + [Path('www/') / arch for arch in ARCHS]
    for mydir in dirs:
        mydir.mkdir(mode=0o755, exist_ok=True, parents=True)
    try:
        symlink(Path('www/archive'), 'updates/archive')
    except FileExistsError:
        pass
checkenv()


def repo_add(fpaths):
    assert type(fpaths) is list
    for fpath in fpaths:
        assert issubclass(type(fpath), os.PathLike) and \
               fpath.name.endswith(f'.pkg.tar.{PKG_COMPRESSION}')
    dbpath = fpath.parent / f'{REPO_NAME}.db.tar.gz'
    return bash(f'{REPO_CMD} {dbpath} {" ".join([str(fpath) for fpath in fpaths])}')

def throw_away(fpath):
    assert issubclass(type(fpath), os.PathLike)
    newPath = Path(abspath).parent / 'recycled' / f"{fpath.name}_{time()}"
    assert not newPath.exists()
    fpath.rename(newPath)

def _check_repo():
    rn = REPO_NAME
    repo_files = (f"{rn}.db {rn}.db.tar.gz {rn}.db.tar.gz.old "
                  f"{rn}.files {rn}.files.tar.gz {rn}.files.tar.gz.old")
    repo_files = repo_files.split(' ')
    repo_files_essential = [fname for fname in repo_files if not fname.endswith('.old')]
    assert repo_files_essential
    # make symlink for arch=any pkgs
    basedir = Path('www') / 'any'
    if basedir.exists():
        for pkgfile in basedir.iterdir():
            if pkgfile.name.endswith(f'.pkg.tar.{PKG_COMPRESSION}') and \
               get_pkg_details_from_name(pkgfile.name).arch == 'any':
                sigfile = Path(f"{str(pkgfile)}.sig")
                if sigfile.exists():
                    logger.info(f'Creating symlink for {pkgfile}, {sigfile}')
                    for arch in ARCHS:
                        if arch == 'any':
                            continue
                        symlink(pkgfile.parent / '..' / arch / pkgfile.name, f'../any/{pkgfile.name}')
                        symlink(sigfile.parent / '..' / arch / sigfile.name, f'../any/{sigfile.name}')
    else:
        logger.error(f'{arch} dir does not exist!')
    # run repo_add
    for arch in ARCHS:
        basedir = Path('www') / arch
        repo_files_count = list()
        pkg_to_add = list()
        if not basedir.exists():
            logger.error(f'{arch} dir does not exist!')
            continue
        pkgfiles = [f for f in basedir.iterdir()]
        for pkgfile in pkgfiles:
            if pkgfile.name in repo_files:
                repo_files_count.append(pkgfile.name)
                continue
            if pkgfile.name.endswith(f'.pkg.tar.{PKG_COMPRESSION}.sig'):
                if not Path(str(pkgfile)[:-4]).exists() and pkgfile.exists():
                    logger.warning(f"{pkgfile} has no package!")
                    throw_away(pkgfile)
                    continue
            elif pkgfile.name.endswith(f'.pkg.tar.{PKG_COMPRESSION}'):
                sigfile = Path(f"{str(pkgfile)}.sig")
                if not sigfile.exists():
                    logger.warning(f"{pkgfile} has no signature!")
                    throw_away(pkgfile)
                    continue
                realarch = get_pkg_details_from_name(pkgfile.name).arch
                if realarch != 'any' and realarch != arch:
                    newpath = pkgfile.parent / '..' / realarch / pkgfile.name
                    assert not newpath.exists()
                    pkgfile.rename(newpath)
                    newSigpath = pkgfile.parent / '..' / realarch / f"{pkgfile.name}.sig"
                    assert not newSigpath.exists()
                    sigfile.rename(newSigpath)
                    logger.info(f'Moving {pkgfile} to {newpath}, {sigfile} to {newSigpath}')
                    pkg_to_add.append(newpath)
                else:
                    pkg_to_add.append(pkgfile)
            else:
                logger.warning(f"{pkgfile} is garbage!")
                throw_away(pkgfile)
        if pkg_to_add:
            logger.info("repo-add: %s", repo_add(pkg_to_add))
        else:
            logger.warning('repo-add: Nothing to do in %s', arch)
        for rfile in repo_files_essential:
            if rfile not in repo_files_count:
                logger.error(f'{rfile} does not exist in {arch}!')

