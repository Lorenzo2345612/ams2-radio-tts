# Piper TTS Microservice

Microservicio de Text-to-Speech optimizado para CPU usando Piper TTS.

## Estructura

```
piper-tts-service/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── app/
│   └── main.py
└── audio/              # Generado automáticamente
```

## Inicio Rápido

```bash
# Construir y ejecutar
docker-compose up -d --build

# Ver logs
docker-compose logs -f

# Detener
docker-compose down
```

## Uso

### Generar Audio

```bash
curl -X POST http://localhost:8000/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, this is a test of the Piper TTS service."}'
```

Respuesta:
```json
{
  "url": "http://localhost:8000/audio/550e8400-e29b-41d4-a716-446655440000.wav"
}
```

### Descargar Audio

```bash
# Obtener URL y descargar
curl -X POST http://localhost:8000/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello world"}' \
  | jq -r '.url' \
  | xargs curl -o output.wav
```

### Health Check

```bash
curl http://localhost:8000/health
```

## Variables de Entorno

| Variable | Default | Descripción |
|----------|---------|-------------|
| `MODEL_PATH` | `/app/models/en_US-lessac-medium.onnx` | Ruta al modelo Piper |
| `BASE_URL` | `http://localhost:8000` | URL base para enlaces de audio |

## Configuración con Reverse Proxy

Para usar detrás de nginx/traefik, ajustar `BASE_URL`:

```yaml
environment:
  - BASE_URL=https://tts.midominio.com
```

Ejemplo nginx:
```nginx
location /tts {
    proxy_pass http://piper-tts:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}

location /audio {
    proxy_pass http://piper-tts:8000;
    proxy_buffering off;  # Streaming
}
```

---

## Recomendaciones

### 1. Limpieza Automática de Audios

Agregar cron job o script de limpieza:

```bash
# Eliminar archivos .wav mayores a 1 hora
find /audio -name "*.wav" -mmin +60 -delete
```

O agregar un servicio en docker-compose:

```yaml
services:
  cleaner:
    image: alpine:latest
    volumes:
      - ./audio:/audio
    entrypoint: /bin/sh -c "while true; do find /audio -name '*.wav' -mmin +60 -delete; sleep 300; done"
```

### 2. Escalabilidad

**Horizontal scaling con múltiples workers:**
```yaml
services:
  piper-tts:
    # ... config existente
    deploy:
      replicas: 3
```

**Load balancer (nginx):**
```nginx
upstream tts_backend {
    least_conn;
    server piper-tts-1:8000;
    server piper-tts-2:8000;
    server piper-tts-3:8000;
}
```

**Cola de mensajes para alto volumen:**
- Usar Redis + Celery/RQ para procesamiento asíncrono
- El endpoint devuelve job_id inmediatamente
- Segundo endpoint para consultar estado

### 3. Almacenamiento S3

Para migrar a S3/MinIO:

```python
# Agregar a requirements.txt:
# boto3==1.34.0

import boto3
from botocore.config import Config

s3 = boto3.client(
    's3',
    endpoint_url=os.getenv('S3_ENDPOINT'),  # MinIO compatible
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    config=Config(signature_version='s3v4')
)

def upload_to_s3(local_path: Path, key: str) -> str:
    bucket = os.getenv('S3_BUCKET', 'tts-audio')
    s3.upload_file(str(local_path), bucket, key)
    # Retornar URL pública o presigned
    return f"{os.getenv('S3_PUBLIC_URL')}/{bucket}/{key}"
```

Variables de entorno para S3:
```yaml
environment:
  - STORAGE_BACKEND=s3
  - S3_ENDPOINT=https://s3.amazonaws.com
  - S3_BUCKET=my-tts-bucket
  - S3_PUBLIC_URL=https://my-tts-bucket.s3.amazonaws.com
  - AWS_ACCESS_KEY_ID=xxx
  - AWS_SECRET_ACCESS_KEY=xxx
```

---

## Modelos Disponibles

Piper soporta múltiples voces. Descargar desde:
https://huggingface.co/rhasspy/piper-voices

Ejemplos:
- `en_US-lessac-medium` (default, ~60MB)
- `en_US-amy-medium`
- `es_ES-davefx-medium` (español)
- `de_DE-thorsten-medium` (alemán)

Para usar otro modelo:
```yaml
volumes:
  - ./my-models:/app/models
environment:
  - MODEL_PATH=/app/models/es_ES-davefx-medium.onnx
```

## Requisitos de Hardware

- **CPU:** x86_64 (ARM no soportado por binario oficial)
- **RAM:** 512MB mínimo, 1GB recomendado
- **Disco:** ~200MB para Piper + modelo
"# ams2-radio-tts" 
