# Tamer
You shouldn't have to jump through hoops to write asynchronous programs. After
all async functions are just functions ... with superpowers. Tamer helps you
unlock these superpowers and turns your pack of async wolfs into a pack of
disciplined async dogs that behave.

**Features**

- [x] 100% pure breed Python
- [x] 100% test coverage
- [x] zero core dependencies 
- [x] small memory footprint
- [x] permissive license (BSD 3-clause)

## Installation
```
pip install tamer
```
... or via your favourite package manager.

## Usage

In a nutshell, you add `@tamed` to an asynchronous function and call it from either
sync and async contexts. Additionally you can assign it to an `AsyncScope` to get
structured lifecycle management.

```python
import asyncio
from tamer import tamed, AsyncScope

@tamed # <-- Notice the decorator
async def slow_echo(msg:str, delay:int) -> None:
    await asyncio.sleep(delay)
    print(msg)

with AsyncScope() as scope:
    slow_echo("scope > DELAY(.2)", .2, _async_scope=scope)
    slow_echo("scope > DELAY(.1)", .1, _async_scope=scope)
# implicit await :)


# Output
# ------
#
# scope > DELAY(.1)
# scope > DELAY(.2)
```

### The `@tamed` decorator
To add more detail, a `@tamed` asynchronous function adapts its execution policy
(how it behaves) depending on the context it is called from. In synchronous
contexts, it behaves like an ordinary function (blocking). In async contexts, it
behaves like an ordinary coroutine (non-blocking), and when assigned to an
`AsyncScope` it listens to the scopes context manager (non-blocking).

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

Since `@tamed` functions know how to behave they also know when (and how) you
expect results to be returned.

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
    handle = slow_io()  # <-- normal coroutine

    return_code, msg = await handle  # <-- await the result
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

From the above, you can see that a `@tamed` function will return an instance of
`DelayedResult` when called with an `AsyncScope`. This object represents the
_result_ of the `@tamed` function and should not be confused with similar
concepts like a `Future`, `asyncio.Task`, or `Coroutine` which represent
asynchronously executing functions. While representing related objects, a
`DelayedResult` is simpler. For example, results don't execute and as such you
can neither cancel them nor can you attach a callback to a completion or failure
event. They (results) are simply values that a function outputs and in the case
of a `DelayedResult` it is simply a result that is late to the party and may not
have arrived just yet.

What you can do with a `DelayedResult` is `await` it in an async context or use
it to `.block()` a synchronous context until it becomes available. Further, you
can inspect it's `.value` (both contexts) which will either return the result or
raise an `AttributeError` if the result is unavailable.

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
    except AttributeError:  # <-- AttributeError if still delayed
        print(f"scope > result: Not yet available.")

    result.block()  # <-- block until result arrives
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
lifecycle. Without going into the weeds, you need to be aware of 3 keywords:

1. Scheduling: Line of code that "unleashes" (starts) a `@tamed` function.
2. Switching: Line of code that switches between sync and async execution.
3. Cleaning: Line of code that deals with async exceptions and errors. 

You handle the _scheduling_ by calling a `@tamed` function with `_async_scope=`
set to a meaningful value; The `AsyncScope` will help with the _switching_ and
_cleaning_. To that end it guarantees that **all functions assigned to a scope
have finished when a scope exits**. To achieve this, it _switches_ to an async
context at the end of the scope and stays there until all its functions
complete. Here, complete does not mean succeed; functions may raise exceptions
or get cancled. This is where the _cleaning_ part comes in which we cover in
"Exception Management".

Additionally, you can nest scopes. `@tamed` functions assigned to an
`outer_scope` execute independelty and alongside `@tamed` functions from an
`inner_scope` whenever _switching_ to an async context occurs. However, since
the `inner_scope` waits for all its functions to complete before _switching_
back to the synchronous context, the _scheduling_ of new functions below an
`inner_scope` will wait, too.

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

As with `@tamed` and `DelayedResult`, this works not just in synchronous
(`with`) contexts but also in asynchronous (`async with`) ones.

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
their kwargs: `exit_mode` and `error_mode`. As the names suggest, the
`exit_mode` controls what happens when the scope exits and the `error_mode`
controls what happens when one of the scope's function produces an error. 

By default these are set to `exit_mode="wait"` and `error_mode="cancel"`. The
former will `"wait"` for unfinished functions at the end of the scope. The
latter will `"cancel"` all functions if one of them fails. This behavior matches
a `asyncio.TaskGroup` or `trio.Nursery`. It is useful when you call functions in
batches, e.g., when making several web API calls or reading a batch of images
from disk.

Alternatively, you can use `exit_mode="cancel"` which will `"cancel"` unfinished
functions at the end of the scope. This is useful when managing functions that
don't terminate, e.g., because they use `while True` somewhere.


```python
import asyncio
from datetime import datetime
from tamer import tamed, AsyncScope

class RateLimiter:
    def __init__(self):
        self.tokens = 3  # initial burst

    @tamed
    async def generate_tokens(self, delay:int):
        while True:  # <-- generate new tokens forever
            await asyncio.sleep(delay)
            self.tokens = min(self.tokens + 1, 3)

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
    # wait for all requests to finish.
# cancel the rate limiter and wait for it to shut down

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
follow suite. There is no difference between them and ordinary functions. You
handle their exceptions the same way you handle exceptions for normal functions;
in the place you retrieve their result.

```python
from tamer import tamed, AsyncScope

@tamed
async def faulty_function()
    raise RuntimeError("Oh no!")

# ============================
# Asynchronous Execution
# ============================

async def main():
    try:
        await faulty_function()
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

The one exception are functions in an `AsyncScope`. Since the result is delayed
(and you get a `DelayedResult`) the exception is too. Like the result, the
exception may arrive at any time after it was scheduled which would cause
problems if your program is currently not ready to handle the exception.
Therefore, contrary to normal exceptions, the exception from a `DelayedResult`
is not raised immediately. Instead, it is raised when you explicitly wait for
the result via `DelayedResult.block()` or via `await delayed_result` depending
on the current context.

The implicit await at the end of an `AsyncScope` acts as a catch-all that raises any
exception that you don't wait for explicitly. This ensures that no exception is
forgotten and that your program doesn't continue in a broken state.

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


### Execution and Lifecycle Management

> **Note**: This section is fairly theoretical and goes deep into the execution
> model of asynchronous programs. It is intended for the curious mind and the
> "low-level hacker". I won't tell anyone if you choose to skip it :)


## FAQ
