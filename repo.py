#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# repo.py: Automatic management tool for an arch repo.
# This file is part of Buildbot by JerryXiao

# Directory structure of the repo:
# buildbot                             -- buildbot (git)
# buildbot/repo                        -- repo root
    # /updates/                        -- new packages goes in here
    # /recycled/                       -- litter bin
    # /archive/                        -- archive dir, old packages goes in here
    # /www/                            -- http server root
    # /www/archive => /archive         -- archive dir for users
    # /www/aarch64                     -- packages for "aarch64"
    # /www/any                         -- packages for "any"
    # /www/armv7h                      -- packages for "armv7h" (No build bot)
    # /www/x86_64                      -- packages for "x86_64"
    # /www/robots.txt => /r_r_n/r.txt  -- robots.txt

import os
from pathlib import Path
from shutil import copyfile as __copy_file
import logging
from utils import bash, Pkg, get_pkg_details_from_name, \
                  print_exc_plus, configure_logger
from time import time

from config import REPO_NAME, PKG_COMPRESSION, ARCHS, REPO_CMD, \
                   REPO_REMOVE_CMD
from shared_vars import PKG_SUFFIX, PKG_SIG_SUFFIX

abspath = os.path.abspath(__file__)
repocwd = Path(abspath).parent / 'repo'
repocwd.mkdir(mode=0o755, exist_ok=True)
os.chdir(repocwd)

logger = logging.getLogger(f'buildbot.{__name__}')


def symlink(dst, src, exist_ok=True):
    assert issubclass(type(dst), os.PathLike) and type(src) is str
    try:
        dst.symlink_to(src)
    except FileExistsError:
        if (not dst.is_symlink()) or (not exist_ok):
            raise

def copyfile(src, dst):
    src = str(src)
    dst = str(dst)
    __copy_file(src, dst, follow_symlinks=False)

def prepare_env():
    dirs = [Path('updates/'), Path('archive/'), Path('recycled/')] + \
           [Path('www/') / arch for arch in ARCHS]
    for mydir in dirs:
        mydir.mkdir(mode=0o755, exist_ok=True, parents=True)
    symlink(Path('www/archive'), '../archive')
prepare_env()


def repo_add(fpaths):
    assert type(fpaths) is list
    assert not [None for fpath in fpaths if fpath.parent != fpaths[0].parent]
    for fpath in fpaths:
        assert issubclass(type(fpath), os.PathLike) and \
               fpath.name.endswith(PKG_SUFFIX)
    dbpath = fpaths[0].parent / f'{REPO_NAME}.db.tar.gz'
    return bash(f'{REPO_CMD} {dbpath} {" ".join([str(fpath) for fpath in fpaths])}', RUN_CMD_TIMEOUT=5*60)

def repo_remove(fpaths):
    assert type(fpaths) is list
    assert not [None for fpath in fpaths if fpath.parent != fpaths[0].parent]
    for fpath in fpaths:
        assert issubclass(type(fpath), os.PathLike) and \
               fpath.name.endswith(PKG_SUFFIX)
    dbpath = fpaths[0].parent / f'{REPO_NAME}.db.tar.gz'
    for fpath in fpaths:
        throw_away(fpath)
        sigpath = fpath.parent / f'{fpath.name}.sig'
        # there is a fscking problem that fscking pathlib always follow symlinks
        if sigpath.exists() or sigpath.is_symlink():
            throw_away(sigpath)
    pkgnames = [get_pkg_details_from_name(fpath.name).pkgname for fpath in fpaths]
    return bash(f'{REPO_REMOVE_CMD} {dbpath} {" ".join(pkgnames)}', RUN_CMD_TIMEOUT=5*60)

def throw_away(fpath):
    assert issubclass(type(fpath), os.PathLike)
    newPath = Path('recycled') / f"{fpath.name}_{time()}"
    assert not newPath.exists()
    logger.warning('Throwing away %s', fpath)
    fpath.rename(newPath)

def archive_pkg(fpath):
    assert issubclass(type(fpath), os.PathLike)
    if fpath.is_symlink():
        logger.warning('Not archiving symlink %s', fpath)
        throw_away(fpath)
        return
    newPath = Path('archive') / fpath.name
    if newPath.exists():
        logger.warning(f'Removing old archive {newPath}')
        throw_away(newPath)
    logger.warning('Archiving %s', fpath)
    fpath.rename(newPath)

def filter_old_pkg(fpaths, keep_new=1, archive=False, recycle=False):
    '''
        Accepts a list of paths (must be in the same dir)
        return a tuple of list of paths
        ([new1, new2], [old1, old2])
        packages are arranged from new to old, one by one.
        new: pkga-v8, pkga-v7, pkgb-v5, pkgb-v4
        old: pkga-v6, pkga-v5, pkgb-v3, pkgb-v2
        (assume keep_new=2)
    '''
    if not fpaths:
        return (list(), list())
    assert type(fpaths) is list
    for fpath in fpaths:
        assert issubclass(type(fpath), os.PathLike) and \
               fpath.name.endswith(PKG_SUFFIX)
    assert not (archive and recycle)
    assert not [None for fpath in fpaths if fpath.parent != fpaths[0].parent]

    new_pkgs = list()
    old_pkgs = list()
    pkgs_vers = dict()
    for fpath in fpaths:
        pkg = get_pkg_details_from_name(fpath.name)
        pkgs_vers.setdefault(pkg.pkgname + pkg.arch, list()).append(pkg)
    for pkgname_arch in pkgs_vers:
        family = pkgs_vers[pkgname_arch]
        # new packages first
        family = sorted(family, reverse=True)
        if len(family) > keep_new:
            new_pkgs += family[:keep_new]
            old_pkgs += family[keep_new:]
        else:
            new_pkgs += family
    for pkg in old_pkgs:
        fullpath = fpaths[0].parent / pkg.fname
        sigpath = fpaths[0].parent / f'{pkg.fname}.sig'
        if archive:
            archive_pkg(fullpath)
            if sigpath.exists():
                archive_pkg(sigpath)
        elif recycle:
            throw_away(fullpath)
            if sigpath.exists():
                throw_away(sigpath)
    return (new_pkgs, old_pkgs)


def _clean_archive(keep_new=3):
    logger.info('starting clean')
    basedir = Path('archive')
    dir_list = [fpath for fpath in basedir.iterdir() if fpath.name.endswith(PKG_SUFFIX)]
    filter_old_pkg(dir_list, keep_new=keep_new, recycle=True)
    logger.info('finished clean')
    return True

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
                sigfile = Path(f"{pkgfile}.sig")
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
        return True
    # run repo_add
    for arch in target_archs:
        basedir = Path('www') / arch
        repo_files_count = list()
        pkgs_to_add = list()
        if not basedir.exists():
            logger.error(f'{arch} dir does not exist!')
            continue
        filter_old_pkg([f for f in basedir.iterdir() if f.name.endswith(PKG_SUFFIX)],
                       keep_new=1, recycle=True)
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
                sigfile = Path(f"{pkgfile}.sig")
                if not sigfile.exists():
                    logger.warning(f"{pkgfile} has no signature!")
                    throw_away(pkgfile)
                    continue
                realarch = get_pkg_details_from_name(pkgfile.name).arch
                if realarch != 'any' and realarch != arch:
                    newpath = pkgfile.parent / '..' / realarch / pkgfile.name
                    newSigpath= Path(f'{newpath}.sig')
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
    logger.info('finished regenerate')
    return True

def _update(overwrite=False):
    logger.info('starting update')
    update_path = Path('updates')
    assert update_path.exists()
    pkgs_to_add = dict()
    filter_old_pkg([f for f in update_path.iterdir() if f.name.endswith(PKG_SUFFIX)],
                   keep_new=1, archive=True)
    for pkg_to_add in update_path.iterdir():
        if pkg_to_add.is_dir():
            continue
        else:
            if pkg_to_add.name.endswith(PKG_SUFFIX):
                sigfile = Path(f"{pkg_to_add}.sig")
                if sigfile.exists():
                    arch = get_pkg_details_from_name(pkg_to_add.name).arch
                    pkg_nlocation = pkg_to_add.parent / '..' / 'www' / arch / pkg_to_add.name
                    sig_nlocation = Path(f'{pkg_nlocation}.sig')
                    logger.info(f'Copying {pkg_to_add} to {pkg_nlocation}, {sigfile} to {sig_nlocation}')
                    if overwrite:
                        for nlocation in (pkg_nlocation, sig_nlocation):
                            if nlocation.exists():
                                logger.warning(f'Overwriting {nlocation}')
                    else:
                        assert not (pkg_nlocation.exists() or sig_nlocation.exists())
                    copyfile(pkg_to_add, pkg_nlocation)
                    copyfile(sigfile, sig_nlocation)
                    archive_pkg(pkg_to_add)
                    archive_pkg(sigfile)
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
    logger.info('finished update')
    return True

def _remove(pkgnames, target_archs=[a for a in ARCHS if a != 'any']):
    assert type(pkgnames) is list and pkgnames
    assert not [None for s in pkgnames if not (type(s) is str)]
    logger.info('starting remove %s for %s', pkgnames, target_archs)
    if len(target_archs) == 1 and target_archs[0] == 'any':
        target_archs = ARCHS
    else:
        assert 'any' not in target_archs
    for arch in target_archs:
        remove_pkgs = list()
        basedir = Path('www') / arch
        for fpath in basedir.iterdir():
            if fpath.name.endswith(PKG_SUFFIX) and \
                get_pkg_details_from_name(fpath.name).pkgname in pkgnames:
                remove_pkgs.append(fpath)
        if remove_pkgs:
            logger.info("repo-remove: %s", repo_remove(remove_pkgs))
        else:
            logger.warning(f'Nothing to remove in {arch}')
    logger.info('finished remove')
    return True

if __name__ == '__main__':
    configure_logger(logger, logfile='repo.log', rotate_size=1024*1024*10)
    import argparse
    try:
        parser = argparse.ArgumentParser(description='Automatic management tool for an arch repo.')
        parser.add_argument('-a', '--arch', nargs='?', default=False, help='arch to regenerate, split by comma, defaults to all')
        parser.add_argument('-o', '--overwrite', action='store_true', help='overwrite when updating existing packages')
        parser.add_argument('-u', '--update', action='store_true', help='get updates from updates dir, push them to the repo')
        parser.add_argument('-r', '--regenerate', action='store_true', help='regenerate the whole package database')
        parser.add_argument('-R', '--remove', nargs='?', default=False, help='remove comma split packages from the database')
        parser.add_argument('-c', '--clean', action='store_true', help='clean archive, keep 3 recent versions')
        args = parser.parse_args()
        arch = args.arch
        arch = arch.split(',') if arch is not False else None
        remove_pkgs = args.remove
        remove_pkgs = remove_pkgs.split(',') if remove_pkgs is not False else None
        if arch is not None:
            assert not [None for a in arch if a not in ARCHS] # ensure arch (= ARCHS
        if args.update:
            _update(overwrite=args.overwrite)
        elif args.regenerate:
            if arch:
                _regenerate(target_archs=arch)
            else:
                _regenerate()
        elif args.clean:
            _clean_archive(keep_new=3)
        elif remove_pkgs:
            if arch:
                _remove(remove_pkgs, target_archs=arch)
            else:
                _remove(remove_pkgs)
        else:
            parser.error("Please choose an action")
    except Exception as err:
        print_exc_plus()
        parser.exit(status=1)
