#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# buildbot.py: Automatic management tool for an arch repo.
# This file is part of Buildbot by JerryXiao

import logging
from multiprocessing.connection import Listener
from time import time, sleep
import os
from pathlib import Path
from shutil import rmtree
from subprocess import CalledProcessError

from shared_vars import PKG_SUFFIX, PKG_SIG_SUFFIX

from config import ARCHS, BUILD_ARCHS, BUILD_ARCH_MAPPING, \
                   MASTER_BIND_ADDRESS, MASTER_BIND_PASSWD, \
                   PKGBUILD_DIR, MAKEPKG_PKGLIST_CMD, MAKEPKG_UPD_CMD, \
                   MAKEPKG_MAKE_CMD, MAKEPKG_MAKE_CMD_CLEAN, \
                   GPG_SIGN_CMD, GPG_VERIFY_CMD, UPDATE_INTERVAL, \
                   MAKEPKG_MAKE_CMD_MARCH, UPLOAD_CMD, \
                   GIT_PULL, GIT_RESET_SUBDIR, CONSOLE_LOGFILE, \
                   MAIN_LOGFILE, PKG_UPDATE_LOGFILE, MAKEPKG_LOGFILE

from utils import print_exc_plus, background, \
                  bash, get_pkg_details_from_name, vercmp, \
                  nspawn_shell, mon_nspawn_shell, get_arch_from_pkgbuild, \
                  configure_logger, mon_bash

from client import run as rrun

import json

from yamlparse import load_all as load_all_yaml

from extra import gen_pkglist as extra_gen_pkglist, \
                  readpkglog as extra_readpkglog, \
                  readmainlog as extra_readmainlog

abspath=os.path.abspath(__file__)
abspath=os.path.dirname(abspath)
os.chdir(abspath)

logger = logging.getLogger('buildbot')
configure_logger(logger, logfile=MAIN_LOGFILE, rotate_size=1024*1024*10, enable_notify=True, consolelog=CONSOLE_LOGFILE)

# refuse to run in systemd-nspawn
if 'systemd-nspawn' in bash('systemd-detect-virt || true'):
    logger.error('Refused to run in systemd-nspawn.')
    raise AssertionError('Refused to run in systemd-nspawn.')

REPO_ROOT = Path(PKGBUILD_DIR)

class Job:
    def __init__(self, buildarch, pkgconfig, version, multiarch=False):
        assert buildarch in BUILD_ARCHS
        self.arch = buildarch
        self.pkgconfig = pkgconfig
        self.version = version
        self.multiarch = multiarch
        self.added = time()
    def __repr__(self):
        ret = "Job("
        for myproperty in (
            'arch', 'pkgconfig', 'version', 'multiarch', 'added'
            ):
            ret += f'{myproperty}={getattr(self, myproperty, None)},'
        ret += ')'
        return ret
    def __lt__(self, job2):
        return self.pkgconfig.priority < job2.pkgconfig.priority
class jobsManager:
    def __init__(self):
        self.__buildjobs = list()
        self.__uploadjobs = list()
        self.__curr_job = None
        self.pkgconfigs = None
        self.last_updatecheck = 0.0
        self.idle = False
    @property
    def jobs(self):
        return \
        {
            'build_jobs': self.__buildjobs,
            'upload_jobs': self.__uploadjobs,
            'current_job': self.__curr_job
        }
    def __repr__(self):
        ret = "jobsManager("
        for myproperty in (
            'jobs', 'pkgconfigs',
            'last_updatecheck', 'idle'
            ):
            ret += f'{myproperty}={getattr(self, myproperty, None)},'
        ret += ')'
        return ret
    def reset_dir(self, pkgdirname=None, all=False, rmpkg=True):
        if all:
            logger.info('resetting %s', str(REPO_ROOT))
            bash(GIT_RESET_SUBDIR, cwd=REPO_ROOT)
        else:
            if not pkgdirname:
                return False
            cwd = REPO_ROOT / pkgdirname
            if cwd.exists():
                logger.info('resetting %s', str(cwd))
                try:
                    bash(GIT_RESET_SUBDIR, cwd=cwd)
                except Exception:
                    logger.error(f'Unable to reset dir {cwd}')
                    print_exc_plus()
                for fpath in [f for f in cwd.iterdir()]:
                    if fpath.is_dir() and \
                            fpath.name in ('pkg', 'src'):
                        if fpath.name == 'pkg':
                            fpath.chmod(0o0755)
                        rmtree(fpath)
                    elif rmpkg and fpath.is_file() and \
                            (fpath.name.endswith(PKG_SUFFIX) or \
                             fpath.name.endswith(PKG_SIG_SUFFIX)):
                        fpath.unlink()
            else:
                return False
        return True
    def force_upload_package(self, pkgdirname, overwrite=False):
        if not self.idle:
            logger.debug('force_upload requested and not idle.')
        if not (REPO_ROOT / pkgdirname).exists():
            ret = f'force_upload failed: no such dir {pkgdirname}'
            logger.warning(ret)
        else:
            self.pkgconfigs = load_all_yaml()
            updates = updmgr.check_update(rebuild_package=pkgdirname)
            if updates and len(updates) == 1:
                (pkgconfig, ver, buildarchs) = updates[0]
                fakejob = Job(buildarchs[0], pkgconfig, ver)
                self.__sign(fakejob)
                if self.__upload(fakejob, overwrite=overwrite):
                    ret = f'done force_upload {pkgdirname}'
                    logger.info(ret)
                else:
                    ret = f'force_upload {pkgdirname} failed: return code.'
                    logger.warning(ret)
            else:
                ret = f'force_upload {pkgdirname} failed: cannot check update.'
                logger.warning(ret)
        return ret
    def rebuild_package(self, pkgdirname, clean=True):
        if not self.idle:
            logger.debug('rebuild requested and not idle.')
        self.pkgconfigs = load_all_yaml()
        if (REPO_ROOT / pkgdirname).exists() and clean:
            self.reset_dir(pkgdirname)
        updates = updmgr.check_update(rebuild_package=pkgdirname)
        if not (REPO_ROOT / pkgdirname).exists():
            ret = f'rebuild failed: no such dir {pkgdirname}'
            logger.warning(ret)
        elif updates and len(updates) == 1:
            (pkgconfig, ver, buildarchs) = updates[0]
            march = True if len(buildarchs) >= 2 else False
            for arch in buildarchs:
                newjob = Job(arch, pkgconfig, ver, multiarch=march)
                self._new_buildjob(newjob)
            ret = f'rebuild job added for {pkgdirname} {" ".join(buildarchs)}'
            logger.info(ret)
        else:
            ret = f'rebuild {pkgdirname} failed: cannot check update.'
            logger.warning(ret)
        return ret
    def _new_buildjob(self, job):
        assert type(job) is Job
        job_to_remove = list()
        for previous_job in self.__buildjobs:
            if job.pkgconfig.dirname == previous_job.pkgconfig.dirname and \
               job.arch == previous_job.arch:
                job_to_remove.append(previous_job)
        for oldjob in job_to_remove:
            self.__buildjobs.remove(oldjob)
            logger.info('removed an old job for %s %s, %s => %s',
                        job.pkgconfig.dirname, job.arch,
                        oldjob.version, job.version)
        logger.info('new job for %s %s %s',
                     job.pkgconfig.dirname, job.arch, job.version)
        self.__buildjobs.append(job)
    def __get_job(self):
        if self.__curr_job:
            logger.error(f'Job {self.__curr_job} failed and is not cleaned.')
            self.__finish_job(self.__curr_job, force=True)
            return self.__get_job()
        jobs = self.__buildjobs
        if jobs:
            jobs.sort(reverse=True)
            self.__curr_job = jobs.pop(0)
            return self.__curr_job
    def __finish_job(self, pkgdir, force=False):
        if not force:
            assert pkgdir == self.__curr_job.pkgconfig.dirname
        self.__curr_job = None
        return True
    def clean_failed_job(self):
        if self.__curr_job:
            logger.error(f'Job {self.__curr_job} failed. Correct the error and rebuild')
            self.__finish_job(self.__curr_job, force=True)
        else:
            raise RuntimeError('Unexpected behavior')
    def __makepkg(self, job):
        cwd = REPO_ROOT / job.pkgconfig.dirname
        if job.multiarch:
            # assume a clean env, no source avail
            mkcmd = MAKEPKG_MAKE_CMD_MARCH
        else:
            mkcmd = MAKEPKG_MAKE_CMD_CLEAN if job.pkgconfig.cleanbuild \
                                        else MAKEPKG_MAKE_CMD
        logger.info('makepkg in %s %s', job.pkgconfig.dirname, job.arch)
        # run pre-makepkg-scripts
        logger.debug('running pre-build scripts')
        for scr in getattr(job.pkgconfig, 'prebuild', list()):
            if type(scr) is str:
                try:
                    mon_nspawn_shell(arch=job.arch, cwd=cwd, cmdline=scr, seconds=60*60)
                except Exception:
                    print_exc_plus()
        # actually makepkg
        try:
            ret = mon_nspawn_shell(arch=job.arch, cwd=cwd, cmdline=mkcmd,
                                    logfile = cwd / MAKEPKG_LOGFILE,
                                    short_return = True,
                                    seconds=job.pkgconfig.timeout*60)
        except Exception:
            logger.error(f'Job {job} failed. Running build-failure scripts')
            for scr in getattr(job.pkgconfig, 'failure', list()):
                if type(scr) is str:
                    try:
                        mon_nspawn_shell(arch=job.arch, cwd=cwd, cmdline=scr, seconds=60*60)
                    except Exception:
                        print_exc_plus()
            raise
        # run post-makepkg-scripts
        logger.debug('running post-build scripts')
        for scr in getattr(job.pkgconfig, 'postbuild', list()):
            if type(scr) is str:
                try:
                    mon_nspawn_shell(arch=job.arch, cwd=cwd, cmdline=scr, seconds=60*60)
                except Exception:
                    print_exc_plus()
        return ret
    def __clean(self, job, remove_pkg=False, rm_src=True):
        cwd = REPO_ROOT / job.pkgconfig.dirname
        logger.info('cleaning build dir for %s, %sremoving pkg',
                    job.pkgconfig.dirname, '' if remove_pkg else 'not ')
        for fpath in [f for f in cwd.iterdir()]:
            if rm_src and fpath.is_dir() and \
                          fpath.name in ('pkg', 'src'):
                rmtree(fpath)
            elif remove_pkg and fpath.is_file() and \
                 ((not job.multiarch) or job.arch in fpath.name) and \
                 (fpath.name.endswith(PKG_SUFFIX) or \
                  fpath.name.endswith(PKG_SIG_SUFFIX)):
                fpath.unlink()
    def __sign(self, job):
        logger.info('signing in %s %s', job.pkgconfig.dirname, job.arch)
        cwd = REPO_ROOT / job.pkgconfig.dirname
        for fpath in cwd.iterdir():
            if fpath.name.endswith(PKG_SUFFIX):
                bash(f'{GPG_SIGN_CMD} {fpath.name}', cwd=cwd)
    def __upload(self, job, overwrite=False):
        cwd = REPO_ROOT / job.pkgconfig.dirname
        f_to_upload = list()
        pkg_update_list = list()
        for fpath in cwd.iterdir():
            if fpath.name.endswith(PKG_SUFFIX) and \
               get_pkg_details_from_name(fpath.name).ver == job.version:
                sigpath = fpath.parent / f'{fpath.name}.sig'
                assert sigpath.exists()
                f_to_upload.append(sigpath)
                f_to_upload.append(fpath)
                pkg_update_list.append(fpath)
        sizes = [f.stat().st_size / 1000 / 1000 for f in f_to_upload]
        pkg_update_list_human = " ".join([f.name for f in pkg_update_list])
        assert pkg_update_list
        max_tries = 10
        for tries in range(max_tries):
            timeouts = rrun('push_start', args=([f.name for f in f_to_upload], sizes))
            if type(timeouts) is list:
                break
            else:
                if tries + 1 < max_tries:
                    logger.warning(f'Remote is busy ({timeouts}), wait 1 min x10 [{tries+1}/10]')
                    sleep(60)
        else:
            raise RuntimeError('Remote is busy and cannot connect')
        assert len(f_to_upload) == len(timeouts)
        pkgs_timeouts = {f_to_upload[i]:timeouts[i] for i in range(len(sizes))}
        for f in f_to_upload:
            max_tries = 5
            for tries in range(max_tries):
                timeout = pkgs_timeouts.get(f)
                try:
                    logger.info(f'Uploading {f.name}, timeout in {timeout}s')
                    mon_bash(UPLOAD_CMD.format(src=f), seconds=int(timeout))
                except Exception:
                    time_to_sleep = (tries + 1) * 60
                    logger.error(f'We are getting problem uploading {f.name}, wait {time_to_sleep} secs')
                    patret = rrun('push_add_time', args=(f.name, time_to_sleep + timeout))
                    if not patret is None:
                        logger.error(f'Unable to run push_add_time, reason: {patret}')
                    print_exc_plus()
                    if tries + 1 < max_tries:
                        sleep(time_to_sleep)
                else:
                    break
            else:
                logger.error(f'Upload {f.name} failed, running push_fail and abort.')
                pfret = rrun('push_fail', args=(f.name,))
                if not pfret is None:
                    logger.error(f'Unable to run push_fail, reason: {pfret}')
                raise RuntimeError('Unable to upload some files')
        logger.info(f'Requesting repo update for {pkg_update_list_human}')
        res = "unexpected"
        max_tries = 5
        for tries in range(max_tries):
            try:
                res = rrun('push_done', args=([f.name for f in f_to_upload],), kwargs={'overwrite': overwrite,})
            except Exception:
                time_to_sleep = (tries + 1) * 60
                logger.info(f'Error updating {pkg_update_list_human}, wait {time_to_sleep} secs')
                print_exc_plus()
                if tries + 1 < max_tries:
                    sleep(time_to_sleep)
            else:
                break
        else:
            ret = f'Update failed for {pkg_update_list_human}: max reties exceeded'
            logger.error(ret)
            raise RuntimeError(ret)
        if res is None:
            logger.info(f'Update success for {pkg_update_list_human}')
        else:
            ret = f'Update failed for {pkg_update_list_human}, reason: {res}'
            logger.error(ret)
            raise RuntimeError(ret)
        return res is None
    def getup(self):
        '''
            check for updates now !!!
        '''
        logger.info('Check for updates now.')
        self.last_updatecheck = 0.0
        return "buildbot wakes up"
    def tick(self):
        '''
            check for updates,
            create new jobs
            and run them
        '''
        if not self.__buildjobs:
            # This part check for updates
            if time() - self.last_updatecheck <= UPDATE_INTERVAL * 60:
                if not self.idle:
                    logger.info('Buildbot is idling for package updates.')
                    self.idle = True
                return 60
            else:
                self.last_updatecheck = time()
                self.idle = False
                # git pull repo
                try:
                    bash(GIT_PULL, cwd=REPO_ROOT)
                except Exception:
                    print_exc_plus()
                self.pkgconfigs = load_all_yaml()
                updates = updmgr.check_update()
                for update in updates:
                    (pkgconfig, ver, buildarchs) = update
                    march = True if len(buildarchs) >= 2 else False
                    for arch in buildarchs:
                        newjob = Job(arch, pkgconfig, ver, multiarch=march)
                        self._new_buildjob(newjob)
                return 0
        else:
            # This part does the job
            self.idle = False
            job = self.__get_job()
            if not job:
                logging.error('No job got')
                return
            if job.multiarch:
                self.__clean(job, remove_pkg=True)
                self.__makepkg(job)
                self.__sign(job)
                if self.__upload(job):
                    self.__clean(job, remove_pkg=True)
            else:
                self.__makepkg(job)
                self.__sign(job)
                if self.__upload(job):
                    if job.pkgconfig.cleanbuild:
                        self.__clean(job, remove_pkg=True)
                    else:
                        self.__clean(job, rm_src=False, remove_pkg=True)
            self.__finish_job(job.pkgconfig.dirname)
            return 0

jobsmgr = jobsManager()

class updateManager:
    def __init__(self, filename='pkgver.json'):
        self.__filename = filename
        self.__pkgerrs = dict()
        self.__pkgvers = dict()
        self.__load()
        self.__rebuilding = False
    @property
    def pkgvers(self):
        return self.__pkgvers
    @property
    def pkgerrs(self):
        return self.__pkgerrs
    def __load(self):
        if Path(self.__filename).exists():
            with open(self.__filename,"r") as f:
                try:
                    pkgdata = json.loads(f.read())
                except json.JSONDecodeError:
                    logger.error('pkgver.json - Bad json')
                    print_exc_plus
                    exit(1)
        else:
            logger.warning(f'No {self.__filename} found')
            pkgdata = dict()
        assert type(pkgdata) is dict
        for pkgname in pkgdata:
            assert type(pkgname) is str
            assert len(pkgdata[pkgname]) == 2
        self.__pkgvers = {pkgname:pkgdata[pkgname][0] for pkgname in pkgdata}
        self.__pkgerrs = {pkgname:pkgdata[pkgname][1] for pkgname in pkgdata}
    def _save(self):
        pkgdata = {pkgname:[self.__pkgvers[pkgname], self.__pkgerrs[pkgname]] for pkgname in self.__pkgvers}
        pkgdatastr = json.dumps(pkgdata, indent=4)
        pkgdatastr += '\n'
        with open(self.__filename,"w") as f:
            if f.writable:
                f.write(pkgdatastr)
            else:
                logger.error('pkgver.json - Not writable')
    def __get_package_list(self, dirname, arch):
        pkgdir = REPO_ROOT / dirname
        assert pkgdir.exists()
        pkglist = nspawn_shell(arch, MAKEPKG_PKGLIST_CMD, cwd=pkgdir, RUN_CMD_TIMEOUT=5*60)
        pkglist = pkglist.split('\n')
        pkglist = [line for line in pkglist if not line.startswith('+')]
        return pkglist
    def __get_new_ver(self, dirname, arch):
        pkgfiles = self.__get_package_list(dirname, arch)
        ver = get_pkg_details_from_name(pkgfiles[0]).ver
        return ver
    def check_update(self, rebuild_package=None):
        updates = list()
        for pkg in jobsmgr.pkgconfigs:
            try:
                if self.__rebuilding and not rebuild_package:
                    logger.info(f'Stop checking updates for rebuild.')
                    break
                else:
                    self.__rebuilding = bool(rebuild_package)
                if rebuild_package and \
                    rebuild_package != pkg.dirname:
                    continue
                pkgdir = REPO_ROOT / pkg.dirname
                logger.info(f'{"[rebuild] " if rebuild_package else ""}checking update: {pkg.dirname}')
                if self.__pkgerrs.get(pkg.dirname, 0) >= 2:
                    logger.warning(f'package: {pkg.dirname} too many failures checking update')
                    if rebuild_package is None:
                        continue
                pkgbuild = pkgdir / 'PKGBUILD'
                archs = get_arch_from_pkgbuild(pkgbuild)
                buildarchs = [BUILD_ARCH_MAPPING.get(arch, None) for arch in archs]
                buildarchs = [arch for arch in buildarchs if arch is not None]
                if not buildarchs:
                    logger.warning(f'No build arch for {pkg.dirname}, refuse to build.')
                    continue
                # hopefully we only need to check one arch for update
                arch = 'x86_64' if 'x86_64' in buildarchs else buildarchs[0] # prefer x86
                # run pre_update_scripts
                logger.debug('running pre-update scripts')
                for scr in getattr(pkg, 'update', list()):
                    if type(scr) is str:
                        mon_nspawn_shell(arch, scr, cwd=pkgdir, seconds=60*60)
                mon_nspawn_shell(arch, MAKEPKG_UPD_CMD, cwd=pkgdir, seconds=5*60*60,
                                logfile = pkgdir / PKG_UPDATE_LOGFILE,
                                short_return = True)
                if pkg.type in ('git', 'manual'):
                    ver = self.__get_new_ver(pkg.dirname, arch)
                    oldver = self.__pkgvers.get(pkg.dirname, None)
                    has_update = False
                    if rebuild_package:
                        has_update = True
                    if oldver:
                        res = vercmp(ver, oldver)
                        if res == 1:
                            has_update = True
                        elif res == -1:
                            logger.warning(f'package: {pkg.dirname} downgrade attempted')
                        elif res == 0:
                            logger.info(f'package: {pkg.dirname} is up to date')
                    else:
                        has_update = True
                    # reset error counter
                    self.__pkgerrs[pkg.dirname] = 0
                    if has_update:
                        self.__pkgvers[pkg.dirname] = ver
                        updates.append((pkg, ver, buildarchs))
                else:
                    logger.warning(f'unknown package type: {pkg.type}')
            except Exception:
                self.__pkgerrs[pkg.dirname] = self.__pkgerrs.get(pkg.dirname, 0) + 1
                print_exc_plus()
        self._save()
        self.__rebuilding = False
        return updates

updmgr = updateManager()




def info(human=False):
    ret = ""
    if human is False:
        ret += str(jobsmgr)
        ret += '\nhuman-readable:\n'
    ret += "".join([f"{k} = {jobsmgr.jobs[k]}\n" for k in jobsmgr.jobs])
    ret += f"idle: {jobsmgr.idle}"
    return ret

def rebuild_package(pkgdirname, clean=False):
    logger.info(f'rebuild command accecpted for {pkgdirname}')
    return jobsmgr.rebuild_package(pkgdirname, clean=clean)

def clean(pkgdirname):
    logger.info(f'clean command accecpted for {pkgdirname}')
    return jobsmgr.reset_dir(pkgdirname=pkgdirname)

def clean_all():
    logger.info('clean command accecpted for all')
    return jobsmgr.reset_dir(all=True)

def force_upload(pkgdirname, overwrite=False):
    logger.info(f'force_upload command accecpted for {pkgdirname}')
    return jobsmgr.force_upload_package(pkgdirname, overwrite=overwrite)

def getup():
    return jobsmgr.getup()

def extras(action, pkgname=None):
    if action.startswith("pkg"):
        p = extra_gen_pkglist(jobsmgr.pkgconfigs, updmgr.pkgvers, updmgr.pkgerrs)
        if action == "pkgdetail":
            return p[1].get(pkgname, None)
        elif action == "pkgdetails":
            return p[1]
        elif action == "pkglist":
            return p[0]
    elif action == "mainlog":
        return extra_readmainlog(debug=False)
    elif action == "debuglog":
        return extra_readmainlog(debug=True)
    elif action == "readpkglog":
        pkgname = str(pkgname)
        return extra_readpkglog(pkgname, update=False)
    elif action == "readpkgupdlog":
        pkgname = str(pkgname)
        return extra_readpkglog(pkgname, update=True)
    return False

def run(funcname, args=list(), kwargs=dict()):
    if funcname in ('info', 'rebuild_package', 'clean', 'clean_all',
                    'force_upload', 'getup', 'extras'):
        logger.debug('running: %s %s %s',funcname, args, kwargs)
        ret = eval(funcname)(*args, **kwargs)
        logger.debug('run: done: %s %s %s',funcname, args, kwargs)
        return ret
    else:
        logger.error('unexpected: %s %s %s',funcname, args, kwargs)
        return False

@background
def __main():
    while True:
        try:
            with Listener(MASTER_BIND_ADDRESS, authkey=MASTER_BIND_PASSWD) as listener:
                with listener.accept() as conn:
                    logger.debug('connection accepted from %s', listener.last_accepted)
                    myrecv = conn.recv()
                    if type(myrecv) is list and len(myrecv) == 3:
                        (funcname, args, kwargs) = myrecv
                        funcname = str(funcname)
                        conn.send(run(funcname, args=args, kwargs=kwargs))
        except Exception:
            print_exc_plus()

if __name__ == '__main__':
    logger.info('Buildbot started.')
    __main() # start the Listener thread
    logger.info('Listener started.')
    while True:
        try:
            try:
                ret = 1
                ret = jobsmgr.tick()
            except Exception:
                jobsmgr.clean_failed_job()
                print_exc_plus()
            if ret is None:
                sleep(1)
            elif ret == 0:
                pass
            elif type(ret) in (int, float):
                sleep(ret)
            else:
                sleep(1)
        except Exception:
            print_exc_plus()
        except KeyboardInterrupt:
            logger.info('KeyboardInterrupt')
            print_exc_plus()
            break
