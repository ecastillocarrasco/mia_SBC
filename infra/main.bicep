// mIA · infraestructura en Azure
// Despliegue:  az deployment group create -g <grupo> -f infra/main.bicep -p infra/main.dev.bicepparam

targetScope = 'resourceGroup'

@description('Entorno: dev o prod')
@allowed(['dev', 'prod'])
param environmentName string

@description('Región de los recursos')
param location string = resourceGroup().location

@description('Prefijo de nombres (minúsculas, sin guiones)')
@minLength(3)
@maxLength(8)
param prefix string = 'mia'

@description('Imagen del contenedor (p. ej. <acr>.azurecr.io/mia:<tag>). Vacío = imagen de prueba')
param containerImage string = ''

@description('SKU de PostgreSQL Flexible Server')
param postgresSku string = 'Standard_B1ms'

@description('Tamaño de almacenamiento de PostgreSQL (GB)')
param postgresStorageGb int = 32

@secure()
@description('Contraseña del administrador de PostgreSQL')
param postgresAdminPassword string

@secure()
@description('Clave del proveedor LLM (Azure OpenAI u OpenAI)')
param llmApiKey string

@description('Proveedor LLM: azure_openai | openai')
param llmProvider string = 'azure_openai'

@description('URL base del LLM (Azure OpenAI: https://<recurso>.openai.azure.com/openai/v1)')
param llmBaseUrl string

@description('Modelo o nombre del despliegue')
param llmModel string = 'gpt-4.1-mini'

@secure()
@description('Clave de ElevenLabs (vacío = voz desactivada)')
param voiceApiKey string = ''

@description('Identificador de la voz de mIA en ElevenLabs')
param voiceId string = ''

@description('Client ID de la app de Entra ID para Easy Auth (vacío = sin Easy Auth; solo dev)')
param easyAuthClientId string = ''

@description('SharePoint: tenant de Entra ID donde está registrada la aplicación')
param sharepointTenantId string = subscription().tenantId

@description('SharePoint: URL del sitio de RRHH (https://<host>/sites/<sitio>)')
param sharepointSiteUrl string = ''

@description('SharePoint: host (<tenant>.sharepoint.com)')
param sharepointHost string = ''

@description('SharePoint: Client ID de la aplicación con acceso al sitio')
param sharepointClientId string = ''

@description('SharePoint: huella del certificado')
param sharepointThumbprint string = ''

@secure()
@description('SharePoint: certificado PFX en base64')
param sharepointPfxBase64 string = ''

@secure()
@description('SharePoint: contraseña del PFX')
param sharepointPfxPassword string = ''

@secure()
@description('Clave HMAC para seudonimizar DNI/NIE (genérala una vez y no la cambies: rompería los cruces)')
param pseudonymKey string

@description('Programación de la sincronización (cron, UTC)')
param syncCron string = '*/10 * * * *'

@description('Réplicas mínimas (1 evita arranques en frío)')
param minReplicas int = 1

var suffix = uniqueString(resourceGroup().id, environmentName)
var name = '${prefix}-${environmentName}'
var tags = { app: 'mia', environment: environmentName }
var isProd = environmentName == 'prod'
var image = empty(containerImage) ? 'mcr.microsoft.com/k8se/quickstart:latest' : containerImage
var voiceEnabled = !empty(voiceApiKey) && !empty(voiceId)
var easyAuthEnabled = !empty(easyAuthClientId)
var sharepointEnabled = !empty(sharepointSiteUrl) && !empty(sharepointPfxBase64)

// ---------------------------------------------------------------- observabilidad
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${name}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${name}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

// ---------------------------------------------------------------- identidad
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${name}'
  location: location
  tags: tags
}

// ---------------------------------------------------------------- secretos
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-${prefix}${environmentName}${take(suffix, 6)}'
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 30
    enablePurgeProtection: isProd ? true : null
  }
}

var keyVaultSecretsUser = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '4633458b-17de-408a-b874-0445c86b69e6'
)

resource vaultAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, identity.id, keyVaultSecretsUser)
  scope: vault
  properties: {
    roleDefinitionId: keyVaultSecretsUser
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------- base de datos
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: 'psql-${name}-${take(suffix, 6)}'
  location: location
  tags: tags
  sku: {
    name: postgresSku
    tier: startsWith(postgresSku, 'Standard_B') ? 'Burstable' : 'GeneralPurpose'
  }
  properties: {
    version: '18'
    administratorLogin: 'miaadmin'
    administratorLoginPassword: postgresAdminPassword
    storage: { storageSizeGB: postgresStorageGb, autoGrow: 'Enabled' }
    backup: { backupRetentionDays: isProd ? 14 : 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: { publicNetworkAccess: 'Enabled' }
  }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'mia'
}

// Acceso solo desde servicios de Azure. Siguiente paso: red privada (VNet) en producción.
resource postgresAzureAccess 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgres
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

var databaseUrl = 'postgresql+asyncpg://miaadmin:${postgresAdminPassword}@${postgres.properties.fullyQualifiedDomainName}:5432/mia?ssl=require'

resource secretDatabase 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'database-url'
  properties: { value: databaseUrl }
}

resource secretLlm 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'llm-api-key'
  properties: { value: llmApiKey }
}

resource secretVoice 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (voiceEnabled) {
  parent: vault
  name: 'voice-api-key'
  properties: { value: voiceApiKey }
}

resource secretPseudonym 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'pseudonym-key'
  properties: { value: pseudonymKey }
}

resource secretPfx 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (sharepointEnabled) {
  parent: vault
  name: 'sharepoint-pfx'
  properties: { value: sharepointPfxBase64, contentType: 'application/x-pkcs12;base64' }
}

resource secretPfxPassword 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (sharepointEnabled) {
  parent: vault
  name: 'sharepoint-pfx-password'
  properties: { value: sharepointPfxPassword }
}

resource secretInsights 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'appinsights-connection-string'
  properties: { value: insights.properties.ConnectionString }
}

// ---------------------------------------------------------------- imágenes
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'cr${prefix}${environmentName}${take(suffix, 6)}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

var acrPull = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')

resource registryAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, acrPull)
  scope: registry
  properties: {
    roleDefinitionId: acrPull
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------- almacenamiento (informes)
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${prefix}${environmentName}${take(suffix, 8)}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource reportsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'informes'
}

var blobContributor = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
)

resource storageAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, identity.id, blobContributor)
  scope: storage
  properties: {
    roleDefinitionId: blobContributor
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------- aplicación
resource appEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${name}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

var baseSecrets = [
  { name: 'database-url', keyVaultUrl: secretDatabase.properties.secretUri, identity: identity.id }
  { name: 'llm-api-key', keyVaultUrl: secretLlm.properties.secretUri, identity: identity.id }
  { name: 'appinsights', keyVaultUrl: secretInsights.properties.secretUri, identity: identity.id }
]
var dataSecrets = [
  { name: 'pseudonym-key', keyVaultUrl: secretPseudonym.properties.secretUri, identity: identity.id }
]
var sharepointSecrets = sharepointEnabled
  ? [
      { name: 'sharepoint-pfx', keyVaultUrl: secretPfx!.properties.secretUri, identity: identity.id }
      { name: 'sharepoint-pfx-password', keyVaultUrl: secretPfxPassword!.properties.secretUri, identity: identity.id }
    ]
  : []
var voiceSecrets = voiceEnabled
  ? [{ name: 'voice-api-key', keyVaultUrl: secretVoice!.properties.secretUri, identity: identity.id }]
  : []

var baseEnv = [
  { name: 'MIA_ENVIRONMENT', value: isProd ? 'production' : 'dev' }
  { name: 'MIA_AUTH__MODE', value: easyAuthEnabled ? 'easyauth' : 'dev' }
  { name: 'MIA_DATABASE_URL', secretRef: 'database-url' }
  { name: 'MIA_LLM__PROVIDER', value: llmProvider }
  { name: 'MIA_LLM__BASE_URL', value: llmBaseUrl }
  { name: 'MIA_LLM__MODEL', value: llmModel }
  { name: 'MIA_LLM__API_KEY', secretRef: 'llm-api-key' }
  { name: 'MIA_OBSERVABILITY__APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'appinsights' }
  { name: 'MIA_VOICE__PROVIDER', value: voiceEnabled ? 'elevenlabs' : 'none' }
  { name: 'MIA_VOICE__VOICE_ID', value: voiceId }
  { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
]
var voiceEnv = voiceEnabled ? [{ name: 'MIA_VOICE__API_KEY', secretRef: 'voice-api-key' }] : []
var dataEnv = [{ name: 'MIA_DATA__PSEUDONYM_KEY', secretRef: 'pseudonym-key' }]
var sharepointEnv = sharepointEnabled
  ? [
      { name: 'MIA_SHAREPOINT__TENANT_ID', value: sharepointTenantId }
      { name: 'MIA_SHAREPOINT__CLIENT_ID', value: sharepointClientId }
      { name: 'MIA_SHAREPOINT__CERT_THUMBPRINT', value: sharepointThumbprint }
      { name: 'MIA_SHAREPOINT__HOST', value: sharepointHost }
      { name: 'MIA_SHAREPOINT__RRHH_SITE_URL', value: sharepointSiteUrl }
      { name: 'MIA_SHAREPOINT__CERT_PFX_BASE64', secretRef: 'sharepoint-pfx' }
      { name: 'MIA_SHAREPOINT__CERT_PFX_PASSWORD', secretRef: 'sharepoint-pfx-password' }
    ]
  : []
var allSecrets = concat(baseSecrets, dataSecrets, sharepointSecrets, voiceSecrets)
var allEnv = concat(baseEnv, dataEnv, sharepointEnv, voiceEnv)

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-${name}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  dependsOn: [vaultAccess, registryAccess]
  properties: {
    managedEnvironmentId: appEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: empty(containerImage) ? [] : [{ server: registry.properties.loginServer, identity: identity.id }]
      secrets: allSecrets
    }
    template: {
      containers: [
        {
          name: 'mia'
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: allEnv
          probes: [
            { type: 'Liveness', httpGet: { path: '/health/live', port: 8000 }, periodSeconds: 30 }
            { type: 'Readiness', httpGet: { path: '/health/ready', port: 8000 }, periodSeconds: 15 }
          ]
        }
      ]
      scale: { minReplicas: minReplicas, maxReplicas: isProd ? 3 : 1 }
    }
  }
}

// Sincronización SharePoint → PostgreSQL: incremental cada 10 minutos, completa una vez al día.
resource syncJob 'Microsoft.App/jobs@2024-03-01' = if (sharepointEnabled && !empty(containerImage)) {
  name: 'caj-${name}-sync'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  dependsOn: [vaultAccess, registryAccess]
  properties: {
    environmentId: appEnvironment.id
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: 1800
      replicaRetryLimit: 1
      scheduleTriggerConfig: { cronExpression: syncCron, parallelism: 1, replicaCompletionCount: 1 }
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
      secrets: allSecrets
    }
    template: {
      containers: [
        {
          name: 'sync'
          image: image
          command: ['python', '-m', 'mia.sync']
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: allEnv
        }
      ]
    }
  }
}

// Easy Auth: login de Entra delante de toda la aplicación hasta implementar MSAL.
resource auth 'Microsoft.App/containerApps/authConfigs@2024-03-01' = if (easyAuthEnabled) {
  parent: app
  name: 'current'
  properties: {
    platform: { enabled: true }
    globalValidation: {
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureactivedirectory'
      excludedPaths: ['/health/live', '/health/ready']
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: easyAuthClientId
          openIdIssuer: '${environment().authentication.loginEndpoint}${subscription().tenantId}/v2.0'
        }
        validation: { allowedAudiences: ['api://${easyAuthClientId}'] }
      }
    }
  }
}

output appUrl string = 'https://${app.properties.configuration.ingress.fqdn}'
output registryLoginServer string = registry.properties.loginServer
output keyVaultName string = vault.name
output postgresHost string = postgres.properties.fullyQualifiedDomainName
