from tamer import tamed, AsyncScope
import asyncio
import pytest
import datetime
import random


def test_syncronous_tame():
    """Tamed functions run syncronously when called directly."""

    @tamed
    async def sleep(duration):
        await asyncio.sleep(duration)

    tic = datetime.datetime.now()
    sleep(0.01)
    toc = datetime.datetime.now()
    assert (toc - tic).total_seconds() >= 0.01


def test_asynchronous_tame():
    """Tamed functions run asynchronously when called from an async function."""

    shared_value = 0

    @tamed
    async def one():
        nonlocal shared_value
        shared_value = 1

    async def race_condition():
        nonlocal shared_value

        handle = one()
        shared_value = 2
        await handle

    asyncio.run(race_condition())
    assert shared_value == 1


def test_DelayedResult():
    @tamed
    async def return_value():
        return True

    with AsyncScope() as scope:
        result = return_value(_async_scope=scope)

        with pytest.raises(AttributeError):
            result.value

    assert result.value


def test_async_execution():
    @tamed
    async def sleep_log(duration):
        await asyncio.sleep(duration)
        return datetime.datetime.now()

    with AsyncScope() as scope:
        second = sleep_log(0.02, _async_scope=scope)
        third = sleep_log(0.03, _async_scope=scope)
        first = sleep_log(0.01, _async_scope=scope)

    assert first.value < second.value < third.value


def test_background_service():
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

    assert three.value == 3
    assert seven.value == 7
    assert ten.value == 10


def test_await_result():
    @tamed
    async def sleep(duration):
        await asyncio.sleep(duration)
        return 42

    with AsyncScope() as scope:
        resultC = sleep(0.03, _async_scope=scope)
        resultA = sleep(0.01, _async_scope=scope)
        resultB = sleep(0.02, _async_scope=scope)

        # no result is ready yet
        for result in [resultA, resultB, resultC]:
            with pytest.raises(AttributeError):
                result.value

        # A and B are ready, but C is not
        resultB.block()
        assert resultA.value == 42
        assert resultB.value == 42
        with pytest.raises(AttributeError):
            resultC.value
    # implicit await for unfinished results

    # all results are ready
    assert resultA.value == 42
    assert resultB.value == 42
    assert resultC.value == 42

def test_simple_retry():
    @tamed
    async def remote_dice(faces:int) -> bool:
        await asyncio.sleep(.1)
        return random.randint(1, faces)

    with AsyncScope(exit_mode="raise") as scope:
        for _ in range(3):
            d6 = remote_dice(6, _async_scope=scope)
            d6.block()
            
            if d6.value == 6:  # success
                print("Winner winner, chicken dinner!")
                break
        else:
            print("Next time bring a lucky coin!")
        
def test_async_scope():
    @tamed
    async def sleep(duration):
        await asyncio.sleep(duration)
        return 42
    
    async def context():
        async with AsyncScope() as scope:
            resultA = sleep(0.01, _async_scope=scope)
            resultB = sleep(0.02, _async_scope=scope)

        assert await resultA == 42
        assert await resultB == 42

    asyncio.run(context())

    