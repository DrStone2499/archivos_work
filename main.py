"""Punto de entrada: Flask en un hilo + ventana pywebview."""
import logging
import sys
import threading

import webview

import settings
from app import config_loader, create_app
from resources import storage_lib
from resources.pipeline import Pipeline

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("relabeler")


def run_server(app):
    app.run(host=settings.HOST, port=settings.PORT,
            threaded=True, debug=False, use_reloader=False)


def main():
    config = config_loader.load()
    storage_lib.init()

    pipeline = Pipeline(config)
    try:
        pipeline.start()
    except Exception as exc:
        log.error("No se pudo iniciar la camara o el modelo: %s", exc)

    app = create_app(pipeline)
    threading.Thread(target=run_server, args=(app,), daemon=True).start()

    window = webview.create_window(
        f"{settings.APP_NAME} {settings.VERSION}",
        f"http://{settings.HOST}:{settings.PORT}",
        width=settings.WINDOW_WIDTH, height=settings.WINDOW_HEIGHT,
        min_size=(1100, 720),
    )

    def on_closed():
        pipeline.stop()

    window.events.closed += on_closed
    webview.start()
    sys.exit(0)


if __name__ == "__main__":
    main()
