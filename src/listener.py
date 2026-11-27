import asyncio
from TikTokLive import TikTokLiveClient
from TikTokLive.types.events import ConnectEvent, CommentEvent, GiftEvent

class LiveClipperListener:
    def __init__(self, unique_id: str):
        self.client: TikTokLiveClient = TikTokLiveClient(unique_id=unique_id)
        self.setup_handlers()

    def setup_handlers(self):
        @self.client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            print(f"Connecte au live de @{self.client.unique_id}")

        @self.client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            print(f"{event.user.nickname}: {event.comment}")

        @self.client.on(GiftEvent)
        async def on_gift(event: GiftEvent):
            if event.gift.streakable and event.gift.repeat_count > 1:
                print(f"DON: {event.user.nickname} a envoye {event.gift.name} x{event.gift.repeat_count}")
            else:
                print(f"DON: {event.user.nickname} a envoye {event.gift.name}")

    def run(self):
        self.client.run()

if __name__ == "__main__":
    streamer_username = "nom_du_streamer"
    clipper_listener = LiveClipperListener(unique_id=streamer_username)
    clipper_listener.run()