"""Almacenamiento de assets y resultados, detrás de UNA interfaz.

Hoy usa el disco local (carpeta data/). Mañana, poniendo STORAGE_BACKEND=gcs
y GCS_BUCKET=..., guarda en Google Cloud Storage SIN tocar el resto del código.

Esto es clave para Cloud Run: el disco de una instancia NO sobrevive al
"escalar a cero", así que lo que deba persistir (lo que sube ella y el reel
final) tiene que ir a GCS. El trabajo temporal de FFmpeg sí puede ser local.

Estructura por sesión:
    <root>/<session_id>/uploads/...   (lo que sube ella)
    <root>/<session_id>/build/...     (temporales de render)
    <root>/<session_id>/out/reel.mp4  (resultado)
"""
import os
import shutil
import uuid

from . import config


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


class Storage:
    """Interfaz mínima. La implementación local basta para empezar."""

    def session_dir(self, session_id: str) -> str:
        raise NotImplementedError

    def save_upload(self, session_id: str, filename: str, data: bytes) -> str:
        raise NotImplementedError

    def build_dir(self, session_id: str) -> str:
        raise NotImplementedError

    def publish_output(self, session_id: str, local_path: str) -> str:
        """Coloca el resultado en su lugar final y devuelve una ruta/URL."""
        raise NotImplementedError


class LocalStorage(Storage):
    def __init__(self, root: str = None):
        self.root = os.path.abspath(root or config.LOCAL_DATA_DIR)
        os.makedirs(self.root, exist_ok=True)

    def session_dir(self, session_id: str) -> str:
        d = os.path.join(self.root, session_id)
        os.makedirs(d, exist_ok=True)
        return d

    def _sub(self, session_id: str, name: str) -> str:
        d = os.path.join(self.session_dir(session_id), name)
        os.makedirs(d, exist_ok=True)
        return d

    def save_upload(self, session_id: str, filename: str, data: bytes) -> str:
        safe = os.path.basename(filename).replace(" ", "_")
        path = os.path.join(self._sub(session_id, "uploads"), safe)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def build_dir(self, session_id: str) -> str:
        return self._sub(session_id, "build")

    def out_dir(self, session_id: str) -> str:
        return self._sub(session_id, "out")

    def publish_output(self, session_id: str, local_path: str) -> str:
        dst = os.path.join(self.out_dir(session_id), os.path.basename(local_path))
        if os.path.abspath(local_path) != os.path.abspath(dst):
            shutil.copy2(local_path, dst)
        return dst


class GCSStorage(LocalStorage):
    """GCS para persistencia real en Cloud Run.

    Sube/baja de un bucket, pero deja el trabajo pesado de FFmpeg en /tmp local
    (rápido). Requiere: pip install google-cloud-storage, y que la cuenta de
    servicio de Cloud Run tenga acceso al bucket.
    """

    def __init__(self, bucket: str = None, root: str = None):
        super().__init__(root=root or "/tmp/reel-studio")
        from google.cloud import storage as gcs  # import perezoso
        self.client = gcs.Client()
        self.bucket = self.client.bucket(bucket or config.GCS_BUCKET)

    def save_upload(self, session_id: str, filename: str, data: bytes) -> str:
        # Guarda local (para que FFmpeg lo lea) y respalda en GCS.
        path = super().save_upload(session_id, filename, data)
        blob = self.bucket.blob(f"{session_id}/uploads/{os.path.basename(path)}")
        blob.upload_from_filename(path)
        return path

    def publish_output(self, session_id: str, local_path: str) -> str:
        dst = super().publish_output(session_id, local_path)
        blob = self.bucket.blob(f"{session_id}/out/{os.path.basename(dst)}")
        blob.upload_from_filename(dst)
        # URL firmada de 24h para vista previa/descarga (el bucket puede ser privado).
        try:
            import datetime
            return blob.generate_signed_url(
                expiration=datetime.timedelta(hours=24), method="GET"
            )
        except Exception:
            return dst  # si no hay credenciales para firmar, cae a ruta local


def get_storage() -> LocalStorage:
    if config.STORAGE_BACKEND == "gcs" and config.GCS_BUCKET:
        return GCSStorage()
    return LocalStorage()
