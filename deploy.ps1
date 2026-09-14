# deploy.ps1 — despliega reel-studio a Google Cloud Run.
# Ejecuta desde C:\dev\reel-studio (donde está el Dockerfile y tu .env).
#   PS> .\deploy.ps1
#
# REQUISITOS PREVIOS (una sola vez):
#   1) Instala Google Cloud SDK (gcloud).
#   2) gcloud auth login    (usa felipevillanueva3000)
#   3) El proyecto DEBE tener FACTURACIÓN activada (tarjeta). El uso normal cae
#      en el tier gratis, pero Cloud Run exige billing vinculado.

# ----- AJUSTA ESTAS 3 LÍNEAS -----
$PROJECT   = "TU_PROJECT_ID"          # míralo con: gcloud projects list
$REGION    = "us-central1"
$APP_PASS  = "PON-UNA-CONTRASENA"     # la clave que escribirá tu esposa al entrar
# ----------------------------------

$SERVICE  = "reel-studio"
$BUCKET   = "reel-studio-media-$PROJECT"
$SA       = "reel-studio-sa"
$SA_EMAIL = "$SA@$PROJECT.iam.gserviceaccount.com"

Write-Host "==> Proyecto: $PROJECT / Región: $REGION" -ForegroundColor Cyan
gcloud config set project $PROJECT

Write-Host "==> Habilitando APIs necesarias..." -ForegroundColor Cyan
gcloud services enable run.googleapis.com cloudbuild.googleapis.com `
  artifactregistry.googleapis.com storage.googleapis.com secretmanager.googleapis.com

Write-Host "==> Creando bucket privado (ignora el error si ya existe)..." -ForegroundColor Cyan
gcloud storage buckets create "gs://$BUCKET" --location=$REGION --uniform-bucket-level-access

Write-Host "==> Guardando la API key de Gemini en Secret Manager (desde tu .env)..." -ForegroundColor Cyan
$key = (Get-Content .env | Where-Object { $_ -match '^GEMINI_API_KEY=' }) -replace '^GEMINI_API_KEY=', ''
if (-not $key) { Write-Error "No encontré GEMINI_API_KEY en .env"; exit 1 }
Set-Content -NoNewline -Path key.tmp -Value $key
# create si no existe; si ya existe, agrega nueva versión
gcloud secrets create GEMINI_API_KEY --data-file=key.tmp 2>$null
gcloud secrets versions add GEMINI_API_KEY --data-file=key.tmp
Remove-Item key.tmp

Write-Host "==> Cuenta de servicio con permisos mínimos..." -ForegroundColor Cyan
gcloud iam service-accounts create $SA 2>$null
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" `
  --member="serviceAccount:$SA_EMAIL" --role="roles/storage.objectAdmin"
gcloud secrets add-iam-policy-binding GEMINI_API_KEY `
  --member="serviceAccount:$SA_EMAIL" --role="roles/secretmanager.secretAccessor"
# Necesario para generar URLs firmadas del bucket desde Cloud Run:
gcloud iam service-accounts add-iam-policy-binding $SA_EMAIL `
  --member="serviceAccount:$SA_EMAIL" --role="roles/iam.serviceAccountTokenCreator"

Write-Host "==> Desplegando (build + deploy). Tarda unos minutos la 1a vez..." -ForegroundColor Cyan
gcloud run deploy $SERVICE `
  --source . `
  --region $REGION `
  --service-account $SA_EMAIL `
  --cpu 2 --memory 4Gi `
  --min-instances 0 --max-instances 3 `
  --concurrency 4 --timeout 900 `
  --session-affinity `
  --set-env-vars "STORAGE_BACKEND=gcs,GCS_BUCKET=$BUCKET,APP_PASSWORD=$APP_PASS" `
  --set-secrets "GEMINI_API_KEY=GEMINI_API_KEY:latest" `
  --allow-unauthenticated

Write-Host "==> Listo. URL del servicio:" -ForegroundColor Green
gcloud run services describe $SERVICE --region $REGION --format="value(status.url)"
