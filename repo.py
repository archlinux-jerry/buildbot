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
from utils import bash, Pkg, get_pkg_details_from_name, print_exc_plus
from time import time
import argparse

from config import REPO_NAME, PKG_COMPRESSION, ARCHS, REPO_CMD
from shared_vars import PKG_SUFFIX, PKG_SIG_SUFFIX

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
    symlink(Path('www/archive'), '../updates/archive')
checkenv()


def repo_add(fpaths):
    assert type(fpaths) is list
    for fpath in fpaths:
        assert issubclass(type(fpath), os.PathLike) and \
               fpath.name.endswith(PKG_SUFFIX)
    dbpath = fpath.parent / f'{REPO_NAME}.db.tar.gz'
    return bash(f'{REPO_CMD} {dbpath} {" ".join([str(fpath) for fpath in fpaths])}', RUN_CMD_TIMEOUT=5*60)

def throw_away(fpath):
    assert issubclass(type(fpath), os.PathLike)
    newPath = Path(abspath).parent / 'recycled' / f"{fpath.name}_{time()}"
    assert not newPath.exists()
    logger.warning('Throwing away %s', fpath)
    fpath.rename(newPath)


def _regenerate(target_archs=ARCHS, just_symlink=False):
    if just_symlink:
        logger.info('starting regenerate symlinks %s', target_archs)
    else:
        logger.info('starting regenerate %s', target_archs)
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
            if pkgfile.name.endswith(PKG_SUFFIX) and \
               get_pkg_details_from_name(pkgfile.name).arch == 'any':
                sigfile = Path(f"{str(pkgfile)}.sig")
                if sigfile.exists():
                    logger.info(f'Creating symlink for {pkgfile}, {sigfile}')
                    for arch in target_archs:
                        if arch == 'any':
                            continue
                        symlink(pkgfile.parent / '..' / arch / pkgfile.name, f'../any/{pkgfile.name}')
                        symlink(sigfile.parent / '..' / arch / sigfile.name, f'../any/{sigfile.name}')
    else:
        logger.error(f'{arch} dir does not exist!')
    if just_symlink:
        return
    # run repo_add
    for arch in target_archs:
        basedir = Path('www') / arch
        repo_files_count = list()
        pkgs_to_add = list()
        if not basedir.exists():
            logger.error(f'{arch} dir does not exist!')
            continue
        pkgfiles = [f for f in basedir.iterdir()]
        for pkgfile in pkgfiles:
            if pkgfile.name in repo_files:
                repo_files_count.append(pkgfile.name)
                continue
            if pkgfile.name.endswith(PKG_SIG_SUFFIX):
                if not Path(str(pkgfile)[:-4]).exists() and pkgfile.exists():
                    logger.warning(f"{pkgfile} has no package!")
                    throw_away(pkgfile)
                    continue
            elif pkgfile.name.endswith(PKG_SUFFIX):
                sigfile = Path(f"{str(pkgfile)}.sig")
                if not sigfile.exists():
                    logger.warning(f"{pkgfile} has no signature!")
                    throw_away(pkgfile)
                    continue
                realarch = get_pkg_details_from_name(pkgfile.name).arch
                if realarch != 'any' and realarch != arch:
                    newpath = pkgfile.parent / '..' / realarch / pkgfile.name
                    newSigpath= Path(f'{str(newpath)}.sig')
                    logger.info(f'Moving {pkgfile} to {newpath}, {sigfile} to {newSigpath}')
                    assert not (newpath.exists() or newSigpath.exists())
                    pkgfile.rename(newpath)
                    sigfile.rename(newSigpath)
                    pkgs_to_add.append(newpath)
                else:
                    pkgs_to_add.append(pkgfile)
            else:
                logger.warning(f"{pkgfile} is garbage!")
                throw_away(pkgfile)
        if pkgs_to_add:
            logger.info("repo-add: %s", repo_add(pkgs_to_add))
        else:
            logger.warning('repo-add: Nothing to do in %s', arch)
        for rfile in repo_files_essential:
            if rfile not in repo_files_count:
                logger.error(f'{rfile} does not exist in {arch}!')

def _update():
    logger.info('starting update')
    update_path = Path('updates')
    assert update_path.exists()
    pkgs_to_add = dict()
    for pkg_to_add in update_path.iterdir():
        if pkg_to_add.is_dir():
            continue
        else:
            if pkg_to_add.name.endswith(PKG_SUFFIX):
                sigfile = Path(f"{str(pkg_to_add)}.sig")
                if sigfile.exists():
                    arch = get_pkg_details_from_name(pkg_to_add).arch
                    pkg_nlocation = pkg_to_add.parent / '..' / 'www' / arch / pkg_to_add.name
                    sig_nlocation = Path(f'{str(pkg_nlocation)}.sig')
                    logger.info(f'Moving {pkg_to_add} to {pkg_nlocation}, {sigfile} to {sig_nlocation}')
                    assert not (pkg_nlocation.exists() or sig_nlocation.exists())
                    pkg_to_add.rename(pkg_nlocation)
                    sigfile.rename(sig_nlocation)
                    if arch == 'any':
                        for arch in ARCHS:
                            pkg_nlocation = pkg_to_add.parent / '..' / 'www' / arch / pkg_to_add.name
                            pkgs_to_add.setdefault(arch, list()).append(pkg_nlocation)
                    else:
                        pkgs_to_add.setdefault(arch, list()).append(pkg_nlocation)
                else:
                    logger.warning(f'{pkg_to_add} has no signature!')
                    throw_away(pkg_to_add)
    if 'any' in pkgs_to_add:
        _regenerate(target_archs=ARCHS, just_symlink=True)
    for arch in pkgs_to_add:
        logger.info("repo-add: %s", repo_add(pkgs_to_add[arch]))
    # remove add other things
    for other in update_path.iterdir():
        if other.is_dir():
            continue
        else:
            logger.warning(f"{other} is garbage!")
            throw_away(other)

if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser(description='Automatic management tool for an arch repo.')
        parser.add_argument('-a', '--arch', nargs='?', default='all', help='arch to regenerate, split by comma, defaults to all')
        parser.add_argument('-u', '--update', action='store_true', help='get updates from updates dir, push them to the repo')
        parser.add_argument('-r', '--regenerate', action='store_true', help='regenerate the whole package database')
        args = parser.parse_args()
        arch = args.arch
        arch = arch.split(',') if arch != 'all' else ARCHS
        assert not [None for a in arch if a not in ARCHS] # ensure arch (= ARCHS
        if args.update:
            _update()
        elif args.regenerate:
            _regenerate(target_archs=arch)
        else:
            parser.error("Please choose an action")
    except Exception as err:
        print_exc_plus()
