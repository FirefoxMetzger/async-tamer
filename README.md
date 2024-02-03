# Async-Tamer
You shouldn't have to split your codebase or jump through hoops just to use
`async def`. After all async functions are just functions ... with superpowers.
Async-Tamer helps you harness these superpowers by seeing `asynd def` for what
they are: A means to flag and reduce periods of busy waiting. (Details at the
end of this readme.)

**Features**

- ✅ 100% python
- ✅ 100% free (BSD 3-clause)
- ✅ 100% lean (no dependencies)

## Installation
```
pip install async-tamer
```

## Usage

In a nutshell, you add `@tamed` to an asynchronous function to enable calling it
directly from either sync and async contexts. You may also assign a `@tamed`
function to an `AsyncScope` to get structured lifecycle management.

```python
import asyncio
from tamer import tamed, AsyncScope

@tamed # <-- Notice the decorator
async def slow_echo(msg:str, delay:int) -> None:
    await asyncio.sleep(delay)
    print(msg)

slow_echo("sync > DELAY(.5)", 0.5)

with AsyncScope() as scope:
    slow_echo("scope > DELAY(.2)", .2, _async_scope=scope)
    slow_echo("scope > DELAY(.1)", .1, _async_scope=scope)
# implicit await :)


# Output
# ------
#
# sync > DELAY(.5)
# scope > DELAY(.1)
# scope > DELAY(.2)
```

### The `@tamed` decorator
A `@tamed` asynchronous function changes its execution policy (how it behaves)
depending on the context it is called from. In synchronous contexts, it behaves
like an ordinary function (blocking). In async contexts, it behaves like an
ordinary coroutine (non-blocking), and when assigned to an `AsyncScope` it
follows the scopes context manager (non-blocking).

```python
import asyncio
from tamer import tamed, AsyncScope

@tamed  # <-- notice the decorator
async def slow_echo(msg:str, delay:int) -> None:
    await asyncio.sleep(delay)
    print(msg)

# ============================
# Asynchronous Execution
# ============================

async def main():
    first = slow_echo("async > DELAY(1)", 1)
    second = slow_echo("async > DELAY(.1)", 0.1)
    third = slow_echo("async > DELAY(.5)", 0.5)

    # Don't forget the await!
    await second
    await asyncio.gather(first, third)

asyncio.run(main())

# Output
# ------
#
# async > DELAY(.1)
# async > DELAY(.5)
# async > DELAY(1)


# ============================
# Synchronous Execution
# ============================

slow_echo("sync > DELAY(1)", 1)
slow_echo("sync > DELAY(.1)", 0.1)
slow_echo("sync > DELAY(.5)", 0.5)

# Output
# ------
#
# sync > DELAY(1)
# sync > DELAY(.1)
# sync > DELAY(.5)

# ============================
# AsyncScope Execution
# ============================

with AsyncScope() as scope:
    slow_echo("scope > DELAY(1)", 1, _async_scope=scope)
    slow_echo("scope > DELAY(.1)", 0.1, _async_scope=scope)
    slow_echo("scope > DELAY(.5)", 0.5, _async_scope=scope)

# Output
# ------
#
# scope > DELAY(.1)
# scope > DELAY(.5)
# scope > DELAY(1)

```

> **Note**: The `_async_scope` kwarg is injected by the `@tamed` decorator and
> is used to add a `@tamed` function to an `AsyncScope`. The reason you may want
> to do this is documented with examples in the `AsyncScope` section.

### Returning Results

`@tamed` functions know when (and how) you expect results to be returned.

```python
import asyncio
from tamer import tamed, AsyncScope

@tamed
async def slow_io():
    await asyncio.sleep(0.1)
    return 200, "Time to be awesome!"

# ============================
# Asynchronous Execution
# ============================

async def main():
    coro = slow_io()  # <-- normal coroutine

    return_code, msg = await coro  # <-- await the result
    print(f"Status {return_code}: `{msg}`")

asyncio.run(main())

# Output
# ------
#
# Status 200: `Time to be awesome!`


# ============================
# Synchronous Execution
# ============================

return_code, msg = slow_io()  # <-- immediate result
print(f"Status {return_code}: `{msg}`")

# Output
# ------
#
# Status 200: `Time to be awesome!`

# ============================
# AsyncScope Execution
# ============================

with AsyncScope() as scope:
    delayed_result = slow_io(_async_scope=scope)
# <-- implicit await on exit

return_code, msg = delayed_result.value
print(f"Status {return_code}: `{msg}`")

# Output
# ------
#
# Status 200: `Time to be awesome!`
```

When called with an `AsyncScope` a `@tamed` function will return an instance of
`DelayedResult`. This object represents the _result_ of the `@tamed` function
and should not be confused with similar concepts like a `Future`,
`asyncio.Task`, or `Coroutine` which represent concurrently executing code.
While those are related objects, a `DelayedResult` is simpler. For example,
unlike code, results don't execute. As such you can't cancel them nor can you
chain callbacks. They (results) are simply values that a function outputs and in
the case of a `DelayedResult` it is a value that arrives late to the party.

What you can do with a `DelayedResult` is `await` it in an async context or use
it to `.block()` a synchronous context until it becomes available. Further, you
can inspect it's `.value` which will either return the result or raise an
`AttributeError` if the result is unavailable.

```python
import asyncio
from tamer import tamed, AsyncScope

@tamed
async def request(delay:int):
    await asyncio.sleep(delay)
    return 200, "You are awesome!"

@tamed
async def post_process(raw_result):
    ret_code, msg = await raw_result  # <-- awaitable in async context
    a, b = msg.rsplit(" ", 1)
    return ret_code, " ".join((a, "very", b))

with AsyncScope() as scope:
    raw_result = request(0.1, _async_scope=scope)
    result = post_process(raw_result, _async_scope=scope)  # <-- pass it around

    try:
        return_code, msg = result.value
    except AttributeError:  # <-- AttributeError, not attived yet
        print(f"scope > result: Not yet available.")

    result.block()  # <-- block in sync context
    return_code, msg = result.value
    print(f"scope > result: Status {return_code}: `{msg}`")

# Output
# ------
#
# scope > result: Not yet available.
# scope > result: Status 200: `You are very awesome!`
```


### The `AsyncScope`

An `AsyncScope` manages a set of `@tamed` functions and controls their
lifecycle. It's a structured way to add async sections to your codebase. Long
story short, you need to be aware of 3 keywords:

1. Scheduling: Line of code that starts a `@tamed` function.
2. Switching: Line of code that switches to another execution context.
3. Cleaning: Line of code that deals with error handling.

You _schedule_ a `@tamed` function by calling it with `_async_scope=` set to a
meaningful value. The `AsyncScope` helps with _switching_ and _cleaning_. To
that end it guarantees that **all functions within the scope have finished when a
scope exits**. To achieve this, it _switches_ between async contexts at the end
of the scope until all its functions complete. Note here that complete does not
mean succeed; functions may raise exceptions or get cancled. This is where the
_cleaning_ part comes in which we cover later during "Exception Management".

Additionally, you can nest scopes. `@tamed` functions assigned to an
`outer_scope` execute independelty and alongside `@tamed` functions from an
`inner_scope` and there can be arbitrary _switching_ between them. However,
since the `inner_scope` waits for all its functions to complete before
_switching_ back to the synchronous context, the _scheduling_ of new functions
below after the `inner_scope` will wait for `inner_scope`'s completion.

```python
import asyncio
from tamer import tamed, AsyncScope

@tamed
async def slow_echo(msg:str, delay:int) -> None:
    await asyncio.sleep(delay)
    print(msg)

with AsyncScope() as outer_scope:
    slow_echo("Outer Scope > DELAY(1.5)", 1.5, _async_scope=outer_scope)
    slow_echo("Outer Scope > DELAY(1)", 1, _async_scope=outer_scope)
    
    with AsyncScope() as inner_scope:
        slow_echo("Outer Scope > Inner Scope > DELAY(2)", 2, _async_scope=inner_scope)
        slow_echo("Outer Scope > Inner Scope > DELAY(1)", 1, _async_scope=inner_scope)
    # await inner_scope functions

    # Note: scheduled after inner scope has finished
    slow_echo("Outer Scope > DELAY(.5)", 0.5, _async_scope=outer_scope)

# Output
# ------
#
# Outer Scope > DELAY(1)
# Outer Scope > Inner Scope > DELAY(1)
# Outer Scope > DELAY(1.5)
# Outer Scope > Inner Scope > DELAY(2)
# Outer Scope > DELAY(.5)

```

Just like `@tamed` and `DelayedResult`, this works not just in synchronous
contexts (`with`) but also in asynchronous ones (`async with`). 

```python
import asyncio
from tamer import tamed, AsyncScope

@tamed
async def slow_echo(msg:str, delay:int) -> None:
    await asyncio.sleep(delay)
    print(msg)

@tamed
async def slow_bulk_echo() -> None:
    async with AsyncScope() as outer_scope:  # <-- `async with` in async contexts
        slow_echo("Outer Scope > DELAY(1.5)", 1.5, _async_scope=outer_scope)
        slow_echo("Outer Scope > DELAY(1)", 1, _async_scope=outer_scope)
        
        async with AsyncScope() as inner_scope:
            slow_echo("Outer Scope > Inner Scope > DELAY(2)", 2, _async_scope=inner_scope)
            slow_echo("Outer Scope > Inner Scope > DELAY(1)", 1, _async_scope=inner_scope)
        # await inner_scope functions

        # Note: scheduled after inner scope has finished
        slow_echo("Outer Scope > DELAY(.5)", 0.5, _async_scope=outer_scope)

slow_bulk_echo()

# Output
# ------
#
# Outer Scope > DELAY(1)
# Outer Scope > Inner Scope > DELAY(1)
# Outer Scope > DELAY(1.5)
# Outer Scope > Inner Scope > DELAY(2)
# Outer Scope > DELAY(.5)
```

The ability to nest `AsyncScopes` is especially useful when you combine it with
its kwargs: `exit_mode` and `error_mode`. As the names suggest, the
`exit_mode` controls what happens when the scope exits and the `error_mode`
controls what happens when an assigned function produces an exception. 

By default these are set to `exit_mode="wait"` and `error_mode="cancel"`. The
former will `"wait"` for unfinished functions at the end of the scope. The
latter will `"cancel"` other unfinished functions if one of them fails. This
behavior matches a `asyncio.TaskGroup` or `trio.Nursery`. It is useful when you
call functions in batches, e.g., when making several web API calls or reading a
batch of images from disk.

Alternatively, you can use `exit_mode="cancel"` which will `"cancel"` unfinished
functions at the end of the scope. This is useful when managing functions that
never terminate, e.g., because they use `while True` somewhere.


```python
import asyncio
from datetime import datetime
from tamer import tamed, AsyncScope

class RateLimiter:
    def __init__(self):
        # allow an initial burst
        self.max_tokens = 3
        self.tokens = self.max_tokens

    @tamed
    async def generate_tokens(self, delay:int):
        while True:  # <-- generate new tokens forever
            await asyncio.sleep(delay)
            self.tokens = min(self.tokens + 1, self.max_tokens)

    @tamed
    async def get_token(self):
        while self.tokens == 0:
            await asyncio.sleep(0)
        self.tokens -= 1
        return True

@tamed
async def fake_request(rate_limiter):
    await rate_limiter.get_token()
    print(datetime.now().strftime("%H:%M:%S.%f"), "Requesting...")

throttle = RateLimiter()
with AsyncScope(exit_mode="cancel") as service_layer:
    throttle.generate_tokens(1, _async_scope=service_layer)

    with AsyncScope() as batch:
        for _ in range(6):
            fake_request(throttle, _async_scope=batch)
    # <-- wait for all requests to finish
# <-- cancel the rate limiter

# Output
# ------
# 00:22:28.348290 Requesting...
# 00:22:28.348436 Requesting...
# 00:22:28.348564 Requesting...
# 00:22:29.347495 Requesting...
# 00:22:30.347555 Requesting...
# 00:22:31.347597 Requesting...
```

### Exception Management
Unfortunately, shit happens. If it does, Python raises an exception and you, the
author of the program, have to decide how to respond. `@tamed` async functions
follow suite and there is no difference between them and ordinary functions.

```python
from tamer import tamed, AsyncScope

@tamed
async def faulty_function()
    raise RuntimeError("Oh no!")

# ============================
# Asynchronous Execution
# ============================

async def main():
    coro = faulty_function()

    try:
        await coro
    except RuntimeError:
        print("Actually, I'm good.")

asyncio.run(main())

# Output
# ------
#
# Actually, I'm good.


# ============================
# Synchronous Execution
# ============================

try:
    faulty_function()
except RuntimeError:
    print("Actually, I'm good.")

# Output
# ------
#
# Actually, I'm good.


# ============================
# AsyncScope Execution
# ============================

with AsyncScope() as scope:
    delayed_result = faulty_function(_async_scope=scope)

    try:
        delayed_result.block()
    except RuntimeError: 
        print("Actually, I'm good.")

# Output
# ------
#
# Actually, I'm good.
```

The one special case are functions in an `AsyncScope`. Here, you consume results
using `DelayedResult.value` but handle exceptions when waiting for a result via
`DelayedResult.block()` or via `await delayed_result`. This is deliberate since
any code following the above statements can now assert that the result has
_successfully_ arrived.

The implicit await at the end of an `AsyncScope` acts as a catch-all that raises
any exceptions that you don't wait for explicitly. This ensures that no exception
is left behind and that your program doesn't produce unintended side-effects.

```python
from tamer import tamed, AsyncScope

@tamed
async def faulty_function()
    raise RuntimeError("Oh no!")

with AsyncScope() as scope:
    result = faulty_function(_async_scope=scope)

# Output (excerpt)
# ----------------
#
# Traceback (most recent call last):
#    [...]
# RuntimeError: Oh no!
```

## Author's Note

> **Note**: This section is quite philosophical and more about why this package
> exists and less about how you use it. It's the "ramblings of an old man",
> so I won't tell anyone if you choose to skip it :)

If you read about python's asyncio library online you will find that people
generally approach the library with a performance mindset. However, only some
actually see this benefits materialize. This results in mixed, but often
negative sentiment about the library ranging from asyncio being "fake
parallelism" or "too complicated to use" to being "useful but very niche".

In my mind, this sentiment typically traces back to three reasons that let users
believe that asyncio should be used like threads:

1. Users think that asyncio uses thread-level parallelism.
2. Asyncio uses thread-like semantics (see the table at the end).
3. A lot of online documentation and tutorials point out that `async/await`
   gives massive performance boosts over thread-based webserver implementations.

Writing asynchronous code while thinking about threads is not wrong ... but it's
incomplete and - in my opinion - missdirected. Why? Because they are two
different kinds of parallelism. Threadding takes a big block of work, slices it
into smaller chunks, and works on multiple of them in parallel across multiple
cores. `Async/await` takes a big block of work, flags periods of busy waiting
and reorders instructions to minimize idle time. In other words, threadding uses
thread-level parallelism (duh!) and `async/await` uses instruction-level parallelism.
Both are forms of parallelism but they are **NOT** the same thing.

|                 | Threads                  | Async/Await          |
| --------------- | -------------------------| -------------------- |
| Orchestration   | Main thread + inf-loop   | Event Loop           |
| Creation        | `tid = Thread(fn, ...)`  | `coro = fn(...)`     |
| Synchronization | `tid.join()`             | `await coro`         |
| Data exchange   | shared memory            | shared memory        |
| Overhead        | ~50 µs (OS level thread) | None (function call) | 
| Concurrency     | preemtive                | cooperative          |


### Implicit Parallelism

Instead of treating `async/await` as multi-threadded code, we should treat it as
code that splits loading and consuming of data. It is aware that input data
comes from external systems (DB, socket, filesystem, blob storage, ...), that
these external systems are slow, and that programs spend most of their time
waiting for data.

Asyncios (clever) trick is to realize that we can only _execute_ instructions
one by one (thank you GIL), but we can _wait_ for any number of external systems in
parallel. Traditional synchronous code asks for a single piece of data, does
nothing while it is being prepared (_busy waiting_), consumes it, and then moves
on to ask for the next piece of data. Async code requests _all_ the data first,
busy waits while it arrives, and then consumes the data one by one without waiting
ever again. This reduces time spent idle from `sum(load_times)` (sync) to
`max(load_times)` (async); a trick known as implicit parallelism.

Further, if our workload allows processing data out of order, we request all
data at the start, busy wait until the first piece arrives, process it, and then
either move to the next piece or resume busy waiting until data arrives again.
This way we spend between `min(load_times)` and `max(load_times)` busy waiting,
which can be a _huge_ speedup compared to `sum(load_times)` in the sync case.

### Why Create Async-Tamer

Realizing how the parallelism behind `async/await` works and moving away from a
thread-like design simplifies the code and its design. Functions that load data
become `async def` and functions that consume the data remain as they were.
Unfortunately, it is not simple to express this with asyncio. We can't use
`await` outside an `async` function and executing an `async` function requires
spinning up an event loop and orchestrating it.

This is why I wrote async-tamer. It limits the extent to which `async`
proliferates through the codebase, i.e., it `@tamed` the `async` keyword ^.^. I
also really like the idea of structured concurrency in trio, which is exactly
what we want when loading a "batch" of data asynchronously before processing it.
However, I think it becomes even more useful if we are able to control the
behavior of the context manager, which is why I added the lifecycle kwargs.

Thanks for reading all the way to the end and happy coding!
