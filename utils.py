#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import subprocess
import logging, logging.handlers
from time import time, sleep
import re
from threading import Thread, Lock
from pathlib import Path
import os
import sys
import traceback

from config import PKG_COMPRESSION, SHELL_ARCH_ARM64, SHELL_ARCH_X64, \
                   SHELL_ARM64_ADDITIONAL, SHELL_TRAP, \
                   CONTAINER_BUILDBOT_ROOT, ARCHS

logger = logging.getLogger(f'buildbot.{__name__}')

def background(func):
    def wrapped(*args, **kwargs):
        tr = Thread(target=func, args=args, kwargs=kwargs)
        tr.daemon = True
        tr.start()
        return tr
    return wrapped

def bash(cmdline, **kwargs):
    assert type(cmdline) is str
    logger.debug(f'bash: {cmdline}, kwargs: {kwargs}')
    return(run_cmd(['/bin/bash', '-x', '-e', '-c', cmdline], **kwargs))

def mon_bash(cmdline, seconds=60*30, **kwargs):
    assert type(seconds) is int and seconds >= 1
    return bash(cmdline, keepalive=True, KEEPALIVE_TIMEOUT=60,
                RUN_CMD_TIMEOUT=seconds, **kwargs)

def nspawn_shell(arch, cmdline, cwd=None, **kwargs):
    root = Path(CONTAINER_BUILDBOT_ROOT)
    if cwd:
        cwd = root / cwd
    else:
        cwd = root
    logger.debug(f'bash_{arch}: {cmdline}, cwd: {cwd}, kwargs: {kwargs}')
    if arch in ('aarch64', 'arm64'):
        command=f'{SHELL_ARM64_ADDITIONAL}; {SHELL_TRAP}; cd \'{cwd}\'; {cmdline}'
        ret = run_cmd(SHELL_ARCH_ARM64 + [command,], **kwargs)
    elif arch in ('x64', 'x86', 'x86_64'):
        command=f'{SHELL_TRAP}; cd \'{cwd}\'; {cmdline}'
        ret = run_cmd(SHELL_ARCH_X64 + [command,], **kwargs)
    else:
        raise TypeError('nspawn_shell: wrong arch')
    if not ret.endswith('++ exit 0\n'):
        raise subprocess.CalledProcessError(1, cmdline, ret)
    return ret

def mon_nspawn_shell(arch, cmdline, cwd, seconds=60*30, **kwargs):
    assert type(seconds) is int and seconds >= 1
    return nspawn_shell(arch, cmdline, cwd=cwd, keepalive=True, KEEPALIVE_TIMEOUT=60,
                        RUN_CMD_TIMEOUT=seconds, **kwargs)

def run_cmd(cmd, cwd=None, keepalive=False, KEEPALIVE_TIMEOUT=30, RUN_CMD_TIMEOUT=60,
            logfile=None, short_return=False):
    logger.debug('run_cmd: %s', cmd)
    RUN_CMD_LOOP_TIME = KEEPALIVE_TIMEOUT - 1 if KEEPALIVE_TIMEOUT >= 10 else 5
    stopped = False
    last_read = [int(time()), ""]
    class Output(list):
        def __init__(self, logfile=None, short_return=False):
            super().__init__()
            self.__short_return = short_return
            if logfile:
                assert issubclass(type(logfile), os.PathLike)
                self.__file = open(logfile, 'w')
            else:
                self.__file = None
        def append(self, mystring):
            if self.__short_return and super().__len__() >= 20:
                super().pop(0)
            super().append(mystring)
            if self.__file and type(mystring) is str:
                self.__file.write(mystring)
                self.__file.flush()
        def __enter__(self):
            return self
        def __exit__(self, type, value, traceback):
            if self.__file:
                self.__file.close()
    stdout_lock = Lock()
    with Output(logfile=logfile, short_return=short_return) as output:
        @background
        def check_stdout(stdout):
            nonlocal stopped, last_read, output
            stdout_lock.acquire()
            last_read_time = int(time())
            while stopped is False:
                line = stdout.readline(4096)
                if line is '':
                    sleep(0.05)
                    continue
                line.replace('\x0f', '\n')
                last_read_time = int(time())
                output.append(line)
                last_read[0] = last_read_time
                last_read[1] = line
            stdout_lock.release()
        p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, encoding='utf-8')
        check_stdout(p.stdout)
        process_start = int(time())
        while True:
            try:
                p.wait(timeout=RUN_CMD_LOOP_TIME)
            except subprocess.TimeoutExpired:
                time_passed = int(time()) - last_read[0]
                if time_passed >= KEEPALIVE_TIMEOUT*2:
                    logger.info('Timeout expired. No action.')
                    output.append('+ Buildbot: Timeout expired. No action.\n')
                elif time_passed >= KEEPALIVE_TIMEOUT:
                    if keepalive:
                        logger.info('Timeout expired, writing nl')
                        output.append('+ Buildbot: Timeout expired, writing nl\n')
                        p.stdin.write('\n')
                        p.stdin.flush()
                    else:
                        logger.info('Timeout expired, not writing nl')
                        output.append('+ Buildbot: Timeout expired, not writing nl\n')
                if int(time()) - process_start >= RUN_CMD_TIMEOUT:
                    stopped = True
                    logger.error('Process timeout expired, terminating.')
                    output.append('+ Buildbot: Process timeout expired, terminating.\n')
                    p.terminate()
                    try:
                        p.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        logger.error('Cannot terminate, killing.')
                        output.append('+ Buildbot: Cannot terminate, killing.\n')
                        p.kill()
                    break
            else:
                # sometimes the process ended too quickly and stdout is not captured
                sleep(0.1)
                stopped = True
                break
        code = p.returncode
        stdout_lock.acquire(10)
        outstr = ''.join(output)

    if code != 0:
        raise subprocess.CalledProcessError(code, cmd, outstr)
    if logfile:
        logger.debug('run_cmd: logfile written to %s', str(logfile))
    else:
        logger.debug('run_cmd: %s, ret = %s', cmd, outstr)
    return outstr


# pyalpm is an alternative
# due to lack of documentation i'll consider this later.

def vercmp(ver1, ver2):
    '''
    compare ver1 and ver2, return 1, -1, 0
    see https://www.archlinux.org/pacman/vercmp.8.html
    '''
    res = run_cmd(['vercmp', str(ver1), str(ver2)])
    res = res.strip()
    if res in ('-1', '0', '1'):
        return int(res)

class Pkg:
    def __init__(self, pkgname, pkgver, pkgrel, arch, fname):
        self.pkgname = pkgname
        self.pkgver = pkgver
        self.pkgrel = pkgrel
        self.arch = arch
        self.fname = fname
        self.ver = f'{self.pkgver}-{self.pkgrel}'
    def __eq__(self, ver2):
        if vercmp(self.ver, ver2.ver) == 0:
            return True
        else:
            return False
    def __ge__(self, ver2):
        return self > ver2 or self == ver2
    def __gt__(self, ver2):
        if vercmp(self.ver, ver2.ver) == 1:
            return True
        else:
            return False
    def __le__(self, ver2):
        return self < ver2 or self == ver2
    def __lt__(self, ver2):
        if vercmp(self.ver, ver2.ver) == -1:
            return True
        else:
            return False
    def __repr__(self):
        return f'Pkg({self.pkgname}, {self.ver}, {self.arch})'


def get_pkg_details_from_name(name):
    assert type(name) is str
    if name.endswith(f'pkg.tar.{PKG_COMPRESSION}'):
        m = re.match(r'(.+)-([^-]+)-([^-]+)-([^-]+)\.pkg\.tar\.\w+', name)
        assert m and m.groups() and len(m.groups()) == 4
        (pkgname, pkgver, pkgrel, arch) = m.groups()
        return Pkg(pkgname, pkgver, pkgrel, arch, name)

def get_arch_from_pkgbuild(fpath):
    assert issubclass(type(fpath), os.PathLike)
    with open(fpath, 'r') as f:
        for line in f.read().split('\n'):
            if line.startswith('arch='):
                matches = re.findall('[()\s\'\"]([\w]+)[()\s\'\"]', line)
                if not matches:
                    raise TypeError('Unexpected PKGBUILD format')
                matches = [arch for arch in matches if arch in ARCHS]
                return matches
    raise TypeError('Unexpected PKGBUILD')

def print_exc_plus():
    logger.log(49, format_exc_plus())

def format_exc_plus():
    """
    Print the usual traceback information, followed by a listing of all the
    local variables in each frame.
    from Python Cookbook by David Ascher, Alex Martelli
    """
    ret = str()
    tb = sys.exc_info()[2]
    while True:
        if not tb.tb_next:
            break
        tb = tb.tb_next
    stack = []
    f = tb.tb_frame
    while f:
        stack.append(f)
        f = f.f_back
    stack.reverse()
    ret += traceback.format_exc()
    ret += "\nLocals by frame, innermost last\n"
    for frame in stack:
        ret += "Frame %s in %s at line %s\n" % (frame.f_code.co_name,
                                                frame.f_code.co_filename,
                                                frame.f_lineno)
        for key, value in frame.f_locals.items(  ):
            ret += "\t%20s = " % key
            # We have to be VERY careful not to cause a new error in our error
            # printer! Calling str(  ) on an unknown object could cause an
            # error we don't want, so we must use try/except to catch it --
            # we can't stop it from happening, but we can and should
            # stop it from propagating if it does happen!
            try:
                ret += str(value)
            except:
                ret += "<ERROR WHILE PRINTING VALUE>"
            ret += '\n'
    return ret

def configure_logger(logger, format='%(asctime)s - %(name)-18s - %(levelname)s - %(message)s',
                     level=logging.INFO, logfile=None, flevel=logging.DEBUG, rotate_size=None,
                     enable_notify=False):
    def __send(*args):
        pass
    if enable_notify:
        try:
            from notify import send
        except ModuleNotFoundError:
            send = __send
    else:
        send = __send

    class ExceptionFormatter(logging.Formatter):
        def __init__(self, *args, notify=False, **kwargs):
            self.notify = notify
            super().__init__(*args, **kwargs)
        def format(self, record):
            if record.levelno == 49:
                record.msg = 'Exception caught.\nPrinting stack traceback\n' + record.msg
            fmtr = super().format(record)
            if self.notify:
                send(fmtr)
            return fmtr

    logger.setLevel(logging.DEBUG)
    fnotify = cnotify = False
    fnotify = True if enable_notify and logfile else False
    cnotify = True if enable_notify and (not logfile) else False
    fformatter = ExceptionFormatter(fmt=format, notify=fnotify)
    cformatter = ExceptionFormatter(fmt=format, notify=cnotify)
    logging.addLevelName(49, 'Exception')
    # create file handler
    if logfile:
        assert type(logfile) is str
        if rotate_size and type(rotate_size) is int and rotate_size >= 1000:
            fh = logging.handlers.RotatingFileHandler(logfile, mode='a',
                                    maxBytes=rotate_size, backupCount=8)
        else:
            fh = logging.FileHandler(logfile)
        fh.setLevel(flevel)
        fh.setFormatter(fformatter)
        logger.addHandler(fh)
    # create console handler
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(cformatter)
    logger.addHandler(ch)
