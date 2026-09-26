using './main.bicep'

param environmentName = 'dev'
param postgresSku = 'Standard_B1ms'
param llmProvider = 'azure_openai'
param llmBaseUrl = 'https://<recurso>.openai.azure.com/openai/v1'
param llmModel = 'gpt-4.1-mini'
// Los secretos se pasan en el despliegue, nunca en este fichero:
//   -p postgresAdminPassword=... llmApiKey=... voiceApiKey=... voiceId=...
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
