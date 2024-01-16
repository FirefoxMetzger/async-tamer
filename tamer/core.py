import asyncio
from functools import wraps
from contextlib import contextmanager
import warnings
from typing import Iterable, Any, Dict, Coroutine
import inspect
from dataclasses import dataclass
import sys


class AwaitError(Exception):
    """Indicates that a tamed async function has not been awaited."""

    pass


@dataclass
class TaskMetadata:
    """Orchestration metadata
    
    This dataclass is used by an AsyncScope to manage the lifecycle of a tamed
    functions.

    """

    frame_info: inspect.FrameInfo
    result: "DelayedResult"


def tamed(fn):
    """Syncronous execution decorator

    This decorator "tames" an asynchronous function (``async def``). This allows
    the function to be executed syncronously when called from syncronous
    contexts and asynchronously when called from asynchronous contexts.

    It also allows adds the special ``_async_scope`` kwarg to the function which
    allows adding it to an ``AsyncScope`` to manage its lifecycle managed.

    Parameters
    ----------
    fn : Callable
        The asynchronous function to tame.

    Notes
    -----
    For syncronous contexts this decorator schedules the function's execution on
    the event loop and blocks until it is completed. If necessary, the event
    loop will be started or created. In this case, it will also be stopped or
    decomissioned afterwards.

    Examples
    --------

    .. code-block:: python

        from syncer import tamed
        import asyncio
        import datetime

        @tamed
        async def sleep(duration):
            await asyncio.sleep(duration)

        tic = datetime.datetime.now()
        sleep(0.5)
        toc = datetime.datetime.now()
        assert (toc - tic).total_seconds() >= 0.5

    """

    @wraps(fn)
    def wrapper(*args, _async_scope: AsyncScope = None, **kwargs):
        coro = fn(*args, **kwargs)
        info = inspect.stack()[1]

        with loop_context() as loop:
            if _async_scope is not None:
                result = _async_scope.insert(coro, frame_info=info)
            elif loop.is_running():
                result = coro
            else:
                result = loop.run_until_complete(coro)

        return result

    return wrapper


class DelayedResult:
    """A asynchronous result.

    An instance of this class is returned by a tamed function that is managed by
    an ``AsyncScope``. The actual result can be obtained syncronously via
    ``DelayedResult.value`` or asynchronously by awaiting this result. Note that
    calling ``DelayedResult.value`` before the function completes will raise an
    ``AttributeError``.

    Examples
    --------
    .. code-block:: python

        from syncer import tamed, AsyncScope

        @tamed
        async def return_value():
            return True

        with AsyncScope() as scope:
            delayed_result = return_value(_async_scope=scope)

            try:
                delayed_result.value
            except AttributeError:
                pass  # result is not yet available

        # result is available after the scope exits
        assert delayed_result.value

    """

    def __init__(self, task: asyncio.Task) -> None:
        self._task = task
        self._awaited = False

    def block(self) -> None:
        """Block until the result is available.
        
        As the name suggests, this is a blocking call. It is used in syncronous
        contexts and yields control to the async context until the function
        producing this result returns.

        Should the function producing this result raise an exception that isn't
        ``asyncio.CancelledError``, the exception will be forwarded to the caller
        of this function.

        Notes
        -----
        In async contexts use ``await delayed_result`` instead.

        Examples
        --------
        This method is useful if your scheduling logic depends on an async
        result, e.g., when implementing a retry mechanism:

        .. code-block:: python

            import asyncio
            import random
            from syncer import tamed, AsyncScope

            @tamed
            async def remote_dice(faces:int) -> bool:
                await asyncio.sleep(.1)
                return random.randint(1, faces)

            with AsyncScope(exit_mode="raise") as scope:
                for _ in range(10):  # 10 attempts
                    d6 = remote_dice(6, _async_scope=scope)
                    d6.block()  # wait for remote to throw the dice
                    
                    if d6.value == 6:  # success
                        print("Winner winner, chicken dinner!")
                        break
                else:
                    print("Next time bring a lucky coin!")

        """

        with loop_context() as loop:
            if loop.is_running():
                raise RuntimeError(
                    "`DelayedResult.block()` can only be used in syncronous contexts."
                )
            self._awaited = True
            loop.run_until_complete(self._task)

        try:
            exception = self._task.exception()
        except asyncio.CancelledError:
            pass
        else:
            if exception is not None:
                raise exception

    @property
    def value(self) -> Any:
        """The result of the asynchronously executed function."""
        if not self._task.done():
            raise AttributeError("Result is not yet available.")
        elif self._task.cancelled():
            raise AttributeError("Execution was cancled.")
        elif self._task.exception() is not None:
            raise AttributeError(
                "Failed to compute result."
            ) from self._task.exception()

        return self._task.result()
    
    @property
    def awaited(self) -> bool:
        """True if ``await`` was called on this result; False otherwise."""
        return self._awaited

    def __await__(self) -> Any:
        """Yield until the result is available."""
        self._awaited = True
        return self._task.__await__()


@contextmanager
def loop_context():
    """Get the event loop.

    Returns a reference to the currently running event loop. If it is closed or
    doesn't yet exist a new loop will be created. Upon completion, this context
    will close the event loop if it was its creator.

    Notes
    -----
    This is an internal helper function. It is not intended to be used directly.

    """

    warnings.filterwarnings("error")
    try:
        # Note: Can't use get_running_loop here. Other code may have
        # scheduled tasks (call_soon) in the current loop, so we
        # can't blindly replace the current event loop.
        loop = asyncio.get_event_loop()
        our_loop = False
    except DeprecationWarning:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        our_loop = True
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        our_loop = True
    else:
        # elif for try ... except anyone?
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            our_loop = True
    warnings.resetwarnings()

    yield loop

    if our_loop:
        loop.close()


class AsyncScope:
    """Lifecycle manager for tamed functions.

    This context manager allows tamed functions to execute concurrently and
    manages their lifecycle. By default it behaves similar to a
    ``asyncio.TaskGroup`` or ``trio.Nursery`` except that it can be called from
    either syncronous or asynchronous contexts. However, you choose what happens
    with functions that haven't returned before the end of the scope (cancel,
    await, ...). Additionally, should a concurrently executing function fail,
    you can configure what should happen to the rest.


    Parameters
    ----------
    exit_mode : str
        Controls how ongoing functions should be handled when the scope exits:
            - ``"wait"`` blocks until all functions finished naturally.
            - ``"cancel"`` cancels all pending functions.
            - ``"raise"`` screams (``AwaitError``) if one or more functions
              haven't returned yet.
    error_mode : str
        Controls the scope's behavior if one of its functions raises an
        exception:
            - ``"cancel"`` will cancel all incomplete functions.
            - ``"continue"`` leaves other tasks untouched.

    Notes
    -----
    While the scope does some exception management, it only handles the
    ``asyncio.CancelledError`` it produces by cancelling onging functions. All
    other exceptions are forwarded to you and you need to decide how to handle
    them.

    Examples
    --------
    Execute a batch of tamed functions concurrently and await their results.
    This mimics ``asyncio.TaskGroup``.

    .. code-block:: python

        from syncer import tamed, AsyncScope
        import datetime

        @tamed
        async def sleep_log(duration):
            await asyncio.sleep(duration)
            return datetime.datetime.now()

        with AsyncScope() as scope:
            second = sleep_log(.02, _async_scope=scope)
            third = sleep_log(.03, _async_scope=scope)
            first = sleep_log(.01, _async_scope=scope)
        # implicitly awaits functions in `scope`

        assert first.value < second.value < third.value

    Run a (unsafe) counter service that is shut down at the end of the scope:

    .. code-block:: python

        from syncer import tamed, AsyncScope

        class CounterService:
            def __init__(self):
                self.state = 0

            @tamed
            async def delay_increment(self, delay):
                while True:
                    await asyncio.sleep(delay)
                    self.state += 1

            @tamed
            async def state_equal(self, min_value):
                while self.state < min_value:
                    await asyncio.sleep(0)
                return self.state


        service = CounterService()
        with AsyncScope(exit_mode="cancel") as service_layer:
            service.delay_increment(0.01, _async_scope=service_layer)
            with AsyncScope() as batch:
                ten = service.state_equal(10, _async_scope=batch)
                three = service.state_equal(3, _async_scope=batch)
                seven = service.state_equal(7, _async_scope=batch)
            # awaits functions in `batch`
        # cancels and shuts down the counter service

        assert three.value == 3
        assert seven.value == 7
        assert ten.value == 10

    """

    def __init__(self, *, exit_mode: str = "wait", error_mode: str = "cancel") -> None:
        self._tasks: Dict[asyncio.Task, TaskMetadata] = {}
        self._loop_ctx = loop_context()
        self._loop: asyncio.AbstractEventLoop = None
        self.closed = False

        # Note: available modes are "wait", "cancel", and "raise"
        self.exit_mode = exit_mode

        # Note: available modes are "cancel" and "continue"
        self.error_mode = error_mode

    def insert(
        self, coro: Coroutine[None, None, Any], frame_info=None
    ) -> DelayedResult:
        """Manage the given coroutine.

        The lifecycle of the provided coroutine will henceforth be managed
        by this scope. It will get scheduled, awaited, and/or cancled depending
        on the settings of this scope.

        Parameters
        ----------
        coro : Coroutine
            The coroutine to manage.
        frame_info : inspect.FrameInfo
            Information on where this coroutine was created. This is useful when
            using ``exit_mode="raise"`` as it allows the scope to point to the
            functions that have not been awaited.

        Notes
        -----
        This is an internal function. You typically won't need to call it directly.

        """

        task = self._loop.create_task(coro)
        task.add_done_callback(self._completion_handler)

        result = DelayedResult(task)
        self._tasks[task] = TaskMetadata(frame_info=frame_info, result=result)
        return result

    def __enter__(self):
        """Attach to the event loop."""

        self._loop = self._loop_ctx.__enter__()
        return self

    async def __aenter__(self):
        """Attach to the event loop."""
        return self.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Detach from the event loop and clean up.

        Notes
        -----
        This is an internal function. You typically won't call it directly.

        This function will fail in an async context.

        """

        # TODO: There should be a refactor where we make both __exit__ and
        # __aexit__ share most of their code paths. I can't see it though.
        raise_await_error = False
        if self.exit_mode == "raise":
            error_msg = "The following async functions were never awaited:"
            for task in self._tasks.keys():
                if self._tasks[task].result.awaited:
                    continue

                raise_await_error = True

                info = self._tasks[task].frame_info
                header = f""" File "{info.filename}", line {info.lineno}, in {info.function}"""
                error_msg += "\n|" + header
                for line in info.code_context:
                    error_msg += f"\n|{line.rstrip()}"
                error_msg += "\n+" + "-" * (len(header) + 1)

        if self.exit_mode in ("cancel", "raise"):
            for task in self._tasks.keys():
                if not task.done():
                    task.cancel()

        self._loop.run_until_complete(self._await_all(self._tasks))
        self._raise_exceptions(exc_val)
        self._loop_ctx.__exit__(exc_type, exc_val, exc_tb)
        self._loop = None
        self.closed = True

        if raise_await_error:
            raise AwaitError(error_msg)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Detach from the event loop and clean up.

        Notes
        -----
        This is an internal function. You typically won't call it directly.

        """

        # TODO: There should be a refactor where we make both __exit__ and
        # __aexit__ share most of their code paths. I can't see it though.
        raise_await_error = False
        if self.exit_mode == "raise":
            error_msg = "The following async functions were never awaited:"
            for task in self._tasks.keys():
                if self._tasks[task].result.awaited:
                    continue

                raise_await_error = True

                info = self._tasks[task].frame_info
                header = f""" File "{info.filename}", line {info.lineno}, in {info.function}"""
                error_msg += "\n|" + header
                for line in info.code_context:
                    error_msg += f"\n|{line.rstrip()}"
                error_msg += "\n+" + "-" * (len(header) + 1)

        if self.exit_mode in ("cancel", "raise"):
            for task in self._tasks.keys():
                if not task.done():
                    task.cancel()

        await self._await_all(self._tasks)
        self._raise_exceptions(exc_val)
        self._loop_ctx.__exit__(exc_type, exc_val, exc_tb)
        self._loop = None
        self.closed = True

        if raise_await_error:
            raise AwaitError(error_msg)

    def _raise_exceptions(self, exc_val):
        """Raise exceptions from failed coroutines.
        
        This function is called when the scope exits. It collects exceptions
        raised by its managed coroutines and jointly raises them as an
        ``ExceptionGroup``.

        Notes
        -----
        When running on pre-3.11 python, this function will chain all exceptions
        into one and will simulate a poor mans "ExceptionGroup". In this case a
        ``RuntimeError`` will be raised.
        
        """
        errors = []
        for task in self._tasks:
            if not task.done():
                continue
            
            if self._tasks[task].result.awaited:
                continue

            try:
                exception = task.exception()
            except asyncio.CancelledError:
                continue
            else:
                if exception is None:
                    continue

            errors.append(exception)

        if len(errors) == 0:
            pass
        elif sys.version_info >= (3, 11):
            raise ExceptionGroup(f"{len(errors)} async functions failed", errors) from exc_val
        else:
            # python 3.10 and below -- poor mans "ExceptionGroup"
            # chain all exceptions and raise them as one
            errors.append(RuntimeError(f"{len(errors)} async functions failed"))
            inverted = [x for x in reversed(errors)]
            for next_error, current_error in zip(inverted[:-1], inverted[1:]):
                next_error.__cause__ = current_error
            raise errors[-1]
            
    async def _await_any(self, task_list: Iterable[asyncio.Task]) -> None:
        """Block until the first task in the list completes."""
        while not any(task.done() for task in task_list):
            await asyncio.sleep(0)  # yeet

    async def _await_all(self, task_list: Iterable[asyncio.Task]) -> None:
        """Block until all tasks in the list complete."""

        for task in task_list:
            try:
                await task
            except asyncio.CancelledError:
                continue
            except Exception as e:
                pass  # will be handled later

    def _completion_handler(self, task: asyncio.Task):
        """Cancel concurrently running functions if one fails.

        This callback is used by ``error_mode="cancel"`` to stop all other tasks
        should one of them fail.

        Notes
        -----
        This is an internal function. You typically won't call it directly.

        """
        if self.error_mode == "continue":
            return

        if task.cancelled():
            return

        if task.exception() is None:
            return

        for task in self._tasks:
            if not task.done():
                task.cancel()
