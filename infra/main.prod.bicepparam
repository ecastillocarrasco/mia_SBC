using './main.bicep'

param environmentName = 'prod'
param postgresSku = 'Standard_B1ms'
param postgresStorageGb = 32
param llmProvider = 'azure_openai'
param llmBaseUrl = 'https://<recurso>.openai.azure.com/openai/v1'
param llmModel = 'gpt-4.1-mini'
// Obligatorio en producción: sin Easy Auth la aplicación no arranca (MIA_AUTH__MODE=dev está bloqueado).
param easyAuthClientId = '<client-id-de-la-app-de-entra>'
param postgresAdminPassword = readEnvironmentVariable('MIA_PG_ADMIN_PASSWORD', '')
param llmApiKey = readEnvironmentVariable('MIA_LLM_API_KEY', '')
param voiceApiKey = readEnvironmentVariable('MIA_VOICE_API_KEY', '')
param voiceId = readEnvironmentVariable('MIA_VOICE_ID', '')
