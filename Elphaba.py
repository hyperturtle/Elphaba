from collections import defaultdict
import uuid
import hashlib
import os
import re
import threading
import time
import random
import shutil
import multiprocessing
import subprocess

class Dfile(object):
    def __init__(self, fullpath):
        self.path = os.path.normpath(fullpath)
        self.pathparts = os.path.split(fullpath)
        self.ext = os.path.splitext(fullpath)
    def __str__(self):
        return self.path
    def change_ext(self, new_ext):
        new = self.ext[0] + '.' + new_ext
        return Dfile(new)
    def append_ext(self, new_ext):
        return Dfile(self.path + '.' + new_ext)

def ant_glob(path):
    path = path.split('/')
    path = map(lambda x: '.*' if x == '**' else re.escape(x).replace('\\*','[^%s]*' % re.escape(os.sep)), path)
    regex = re.compile('.' + re.escape(os.sep) + ''.join(path) + '$')
    for root, folder, files in os.walk('.'):
        for fi in files:
            fullpath = os.path.join(root,fi)
            if regex.match(fullpath):
                yield Dfile(fullpath)

class Task(object):
    def __init__(self):
        self.froms = []
        self.to = 0
        self.inprogress = False

class DAG(object):
    def __init__(self, fr=defaultdict(dict), tasks=defaultdict(Task)):
        self.fr = fr
        self.tasks = tasks
        self.lock = threading.Lock()
    def add_edge(self, fr, to, task):
        self.fr[to][fr] = task
        self.tasks[task].froms.append(fr)
        self.tasks[task].to = to
    def del_task(self, task):
        to = self.tasks[task].to
        assert(self.tasks[task].inprogress)
        self.lock.acquire()
        del self.fr[to]
        del self.tasks[task]
        self.lock.release()
    def get_task(self, task):
        return self.tasks[task]
    def oneleaf(self):
        self.lock.acquire()
        for task in filter(lambda x: not self.tasks[x].inprogress, self.tasks):
            if self.tasks[task].to not in self.fr:
                continue
            for fr in self.tasks[task].froms:
                if fr in self.fr:
                    break
            else:
                self.lock.release()
                return task
        self.lock.release()
    def start(self, leaf):
        self.lock.acquire()
        self.tasks[leaf].inprogress = True
        self.lock.release()
    def copy(self):
        r = DAG(fr=self.fr.copy(), tasks = self.tasks.copy())
        return r

class Elphaba(object):
    def __init__(self):
        self.dag = DAG()
        self.tasks = []
        self.files = []
        self.handlers = {}
        self.handler_lock = threading.Semaphore(multiprocessing.cpu_count())
        self.build_prefix = 'build'
        self.tmp_prefix = os.path.join(self.build_prefix,'tmp')
    def built(self, filename):
        return os.path.join(self.build_prefix, filename)
    def system(self, *args):
        return subprocess.call(args, shell=True)
    def on(self, name):
        def wrap(fn):
            def fn2(from_files, to_file, localdag, leaf, *args):
                try:
                    if not os.path.exists(os.path.dirname(to_file)):
                        os.makedirs(os.path.dirname(to_file))
                    fn(from_files, to_file, *args)
                    assert(os.path.exists(to_file))
                    localdag.del_task(leaf)
                finally:
                    self.handler_lock.release()
            self.handlers[name] = fn2
            return fn2
        return wrap
    def tmp(self, fr, task):
        m = hashlib.sha512(task + ''.join(str(fr))).hexdigest()[:20]
        m = os.path.join(self.tmp_prefix, m)
        while m in self.files:
            m = hashlib.sha224(m + task + ''.join(str(fr))).hexdigest()[:20]
            m = os.path.join(self.tmp_prefix, m)
        return m
    def build(self, task, frs, to = None, args=()):
        frs = map(str, frs)
        frs = map(os.path.normpath, frs)
        from_files = []
        for fr in frs:
            if fr in self.files:
                fr = self.files.index(str(fr))
            else:
                self.files.append(str(fr))
                fr = len(self.files) - 1
            from_files.append(fr)

        if to == None:
            to = self.tmp(frs,task)
        else:
            to = os.path.normpath(os.path.join(self.build_prefix, str(to)))
        if to in self.files:
            raise Exception('{0} already has a task associated'.format(to))

        self.files.append(to)
        to = len(self.files) - 1

        for fr in from_files:
            self.dag.add_edge(fr, to, len(self.tasks))

        self.tasks.append(task)

        return self.files[to]
    def debug(self):
        localdag = self.dag.copy()
        while len(localdag.tasks) > 0:
            leaf       = localdag.oneleaf()
            if leaf == None:
                self.handler_lock.acquire()
                self.handler_lock.release()
                continue
            if self.tasks[leaf] not in self.handlers:
                raise Exception('Handler for {0} was not found')
            task       = localdag.tasks[leaf]
            handler    = self.handlers[self.tasks[leaf]]
            from_files = map(lambda x:self.files[x],task.froms)
            to_file    = self.files[task.to]

            status = dict()
            status['progress'] = '{0}%'.format(100 * (len(self.dag.tasks) - len(localdag.tasks)) / len(self.dag.tasks))
            status['currenttask'] = self.tasks[leaf]
            status['inputfiles'] = ', '.join(map(str, from_files))
            status['outputfile'] = to_file

            print('{progress:>3}| {currenttask:>12} {inputfiles:<35} > {outputfile}'.format(**status))

            self.handler_lock.acquire()
            thread = threading.Thread(target=handler, args=(from_files, to_file, localdag, leaf))
            localdag.start(leaf)
            thread.start()



elph = Elphaba()
cssfiles = []
cssfiles.append(elph.build('less', ['assets/css/styles.less']))
cssfiles.append(elph.build('less', ['assets/css/styles.less']))
cssfiles.append(elph.build('less', ['assets/css/styles.less']))
coffeefiles = []
for coffee in ant_glob('assets/**/*.coffee'):
    coffeefiles.append(elph.build('coffeescript', [coffee]))

elph.build('concat', coffeefiles, 'out.js')
elph.build('concat', cssfiles, 'out.css')
elph.build('uglify', [elph.built('out.js')], 'out.min.js')


@elph.on('coffeescript')
def coffeescript(from_files, to_file):
    time.sleep(random.random())
    with open(from_files[0], 'r') as f:
        with open(to_file, 'w') as outf:
            subprocess.Popen(["coffee","-c","-s"],stdin=f, stdout=outf, shell=True).wait()

@elph.on('concat')
def concat(from_files, to_file):
    with file(to_file, 'wb') as f:
        for filename in from_files:
            with open(filename, 'rb') as input_file:
                shutil.copyfileobj(input_file, f)

@elph.on('uglify')
def uglify(from_files, to_file):
    time.sleep(random.random())
    with file(to_file, 'w') as outf:
        subprocess.Popen(["uglifyjs", from_files[0]], stdout=outf, shell=True).wait()

@elph.on('less')
def less(from_files, to_file):
    time.sleep(random.random())
    with open(to_file, 'w') as outf:
        cwd=os.path.dirname(from_files[0])
        subprocess.Popen(["lessc","-x",os.path.relpath(from_files[0],cwd)],cwd=cwd, stdout=outf, shell=True).wait()


elph.debug()




