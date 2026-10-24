using './main.bicep'

param environmentName = 'prod'
param postgresSku = 'Standard_B1ms'
param postgresStorageGb = 32
param llmProvider = 'azure_openai'
param llmBaseUrl = 'https://<recurso>.openai.azure.com/openai/v1'
param llmModel = 'gpt-4.1-mini'
// Client ID de CV-SunsetBeachClub (API y cliente confidencial OBO).
param easyAuthClientId = '<client-id-de-la-app-de-entra>'
// Activar solo después de configurar scope access_as_user, certificado y permisos Graph delegados.
param delegatedMailEnabled = false
// IDs públicos de los dos clientes que solicitarán access_as_user a la API CV-SunsetBeachClub.
param entraWebClientId = readEnvironmentVariable('MIA_ENTRA_WEB_CLIENT_ID', '')
param entraDesktopClientId = readEnvironmentVariable('MIA_ENTRA_DESKTOP_CLIENT_ID', '')
param postgresAdminPassword = readEnvironmentVariable('MIA_PG_ADMIN_PASSWORD', '')
param llmApiKey = readEnvironmentVariable('MIA_LLM_API_KEY', '')
param voiceApiKey = readEnvironmentVariable('MIA_VOICE_API_KEY', '')
param voiceId = readEnvironmentVariable('MIA_VOICE_ID', '')
param pseudonymKey = readEnvironmentVariable('MIA_PSEUDONYM_KEY', '')
param sharepointSiteUrl = 'https://sunsetbeachclub.sharepoint.com/sites/<sitio-rrhh>'
param sharepointHost = 'sunsetbeachclub.sharepoint.com'
param sharepointClientId = '<client-id-de-la-app-de-sharepoint>'
param sharepointThumbprint = '<huella-del-certificado>'
param sharepointPfxBase64 = readEnvironmentVariable('MIA_SHAREPOINT_PFX_BASE64', '')
param sharepointPfxPassword = readEnvironmentVariable('MIA_SHAREPOINT_PFX_PASSWORD', '')
