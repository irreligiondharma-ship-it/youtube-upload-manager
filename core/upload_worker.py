import threading

from core.uploader import Uploader


class UploadWorker(threading.Thread):
    def __init__(self, youtube_client, account_name=None, progress_callback=None, excel_file=None, videos_dir=None, thumbnails_dir=None):
        super().__init__(daemon=True)
        self.uploader = Uploader(
            youtube_client=youtube_client,
            account_name=account_name,
            progress_callback=progress_callback,
            excel_file=excel_file,
            videos_dir=videos_dir,
            thumbnails_dir=thumbnails_dir,
        )

    def run(self):
        self.uploader.start()

    def stop(self):
        self.uploader.stop()

    def pause(self):
        self.uploader.pause()

    def resume(self):
        self.uploader.resume()
