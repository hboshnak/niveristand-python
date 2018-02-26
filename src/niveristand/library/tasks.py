from collections import deque
from contextlib import contextmanager
import inspect
import logging
from threading import current_thread, Event, Thread
from niveristand import errormessages, exceptions

_scheduler = None


def get_scheduler():
    global _scheduler
    if _scheduler is None:
        _scheduler = _Scheduler()
    return _scheduler


@contextmanager
def multitask():
    multitask_info = _MultiTaskInfo()
    yield multitask_info
    # for a multitask the children need to be added to the queue ahead of the rest of the parent's tasks.
    # So here we reverse the list and add the tasks at the top because we don't know how far the bottom is.
    list.reverse(multitask_info.tasks)
    for task in multitask_info.tasks:
        get_scheduler().register_task_at_top(task)

    for task in multitask_info.tasks:
        task.start()

    while not multitask_info.finished:
        nivs_yield()


def nivs_yield():
    s = get_scheduler()
    task = s.thread_yielded()
    s.sched()
    if not task.is_stopped():
        task.wait_for_turn()


class _MultiTaskInfo:
    task_id = 0

    def __init__(self):
        self.tasks = []

    def add_func(self, func):
        task = _Task(func, parent=self)
        self.tasks.append(task)

    @property
    def finished(self):
        return all([t.is_stopped() for t in self.tasks])

    @classmethod
    def get_unique_task_name(cls):
        cls.task_id += 1
        return str(cls.task_id)


class _Task:
    def __init__(self, func, parent=None):
        if inspect.isfunction(func) or inspect.ismethod(func):
            self._task_name = func.__name__
            self._thread = Thread(
                target=func,
                args=(self,),
                name=self._task_name + '_' + _MultiTaskInfo.get_unique_task_name())
        else:
            self._thread = current_thread()
            self._task_name = str(func)
        self._stopped = False
        self._state_signal = Event()
        self._parent = parent

    def start(self):
        self._thread.start()

    @property
    def parent(self):
        return self._parent

    @property
    def thread(self):
        return self._thread

    def is_stopped(self):
        return self._stopped

    def wait_for_turn(self):
        return self._state_signal.wait()

    def signal_to_run(self):
        self._state_signal.set()

    def move_to_ready(self):
        self._state_signal.clear()

    def mark_stopped(self):
        self._stopped = True

    def __repr__(self):
        return "Task:name={} thread={}".format(self._task_name, str(self._thread))

    def __str__(self):
        return "Task:name={}".format(self._task_name)


class _Scheduler:
    def __init__(self):
        # a dictionary of {threadID:  _Task()}
        self._task_dict = dict()
        self._task_queue = deque()
        self._log = logging.getLogger('<sched>')

    def sched(self):
        self._log.debug("Enter sched")
        # if there are no more tasks to run, return False
        try:
            # find the next task in the queue.
            next_task = self._task_queue.popleft()
            # then tell it to run
            self._log.debug("Next task:%s", str(next_task))
            next_task.signal_to_run()
        except IndexError:
            # there was no work to do, but it's not fatal.
            return False
        return True

    def thread_yielded(self):
        task = self.get_task_for_curr_thread()
        self._log.debug("Task yielded:%s", str(task))
        # mark the yielding task ready to run
        task.move_to_ready()
        # finally, if this thread is not finished, add it to the run queue
        if not task.is_stopped():
            self._log.debug("Reschedule Task :%s", str(task))
            self._task_queue.append(task)
        else:
            self._log.debug("Finished Task :%s", str(task))
            self.task_finished(task)
        return task

    def register_task_at_top(self, task):
        self._register_task_core(task, True)

    def register_task(self, task):
        self._register_task_core(task, False)

    def _register_task_core(self, task, at_top):
        self._task_dict[task.thread] = task
        self._log.debug("Register Task :%s", (str(task)))
        if at_top:
            self._task_queue.appendleft(task)
        else:
            self._task_queue.append(task)

    def task_finished(self, task):
        del self._task_dict[task.thread]

    def create_task_for_curr_thread(self):
        thread = current_thread()
        if thread in self._task_dict:
            raise exceptions.VeristandError(errormessages.reregister_thread)
        task = _Task(thread.getName())
        return task

    def get_task_for_curr_thread(self):
        thread = current_thread()

        if thread not in self._task_dict:
            raise exceptions.VeristandError(errormessages.unregistered_thread)
        return self._task_dict[thread]

    def try_get_task_for_curr_thread(self):
        try:
            task = self.get_task_for_curr_thread()
        except exceptions.VeristandError:
            task = None
        return task


def stop_task():
    pass