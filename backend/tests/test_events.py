import asyncio

from events import ProfileEventBroker


def test_event_broker_delivers_only_matching_scholar():
    async def exercise():
        broker = ProfileEventBroker(None)
        queue = broker.subscribe("scholar-1")
        broker._publish({"scholar_id": "scholar-2", "version": 1})
        assert queue.empty()

        event = {"scholar_id": "scholar-1", "version": 2, "status": "ready"}
        broker._publish(event)
        received = await asyncio.wait_for(queue.get(), timeout=1)
        broker.unsubscribe("scholar-1", queue)
        return received

    assert asyncio.run(exercise()) == {
        "scholar_id": "scholar-1",
        "version": 2,
        "status": "ready",
    }
