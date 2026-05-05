---
title: Replace this text based on the guidance in Completing the metadata under the Article Title section.   
description: Replace this text based on the guidance in Completing the metadata under the Article Title section.
keywords: Replace this text based on the guidance in Completing the metadata under the Article Title section.
ms.service: dynamics-365 #Required. Leave as-is for all things Dynamics 365, but change to dccp for DCCP content.
ms.subservice: guidance #Required. Leave as-is.
ms.topic: conceptual #Required. Leave as-is.
ms.custom: bap-template #Required; Leave as-is.
author: #Required; your GitHub user alias, with correct capitalization. 
ms.date: 08/22/2023
---

# Article title as a noun phrase

*GMS MailBox Agent*

This solution is a generalized architecture pattern, which can be used for many different scenarios and industries. See the following example solutions that build off of this core architecture:

- [Link to first solution idea or other architecture that builds off this solution](https://learn.microsoft.com/en-us/dynamics365/guidance/)

## Architecture

*Architecture diagram goes here. Under the architecture diagram, include this sentence and a link to the Visio file or the PowerPoint file:*

Download a [PowerPoint file](https://github.com/Saphgit/dynamics365patternspractices/blob/sapharchitecture/architectures/gmsmailbox_design.pptx) with this architecture.

### Dataflow

The GMS Mailbox Agent data flow begins when an external sender submits an email to the GMS shared mailbox hosted in Exchange Online. Dynamics 365 Customer Service ingests the mailbox email using standard mailbox processing and creates or updates a Case, with the email stored as a related activity record. Dynamics 365 acts as the system of record for all mailbox interactions and case lifecycle management.
Case creation triggers a Power Automate parent orchestration flow. The flow reads the case and email content, derives the EngagementID, and persists normalized email metadata and extracted content into Microsoft Dataverse. Dataverse serves as the secure, auditable data layer, enforcing row level security to ensure all downstream processing is strictly scoped to the relevant engagement.
The orchestration then invokes a Copilot Studio agent action to perform AI assisted classification and intent detection. The agent reads only engagement scoped records from Dataverse and returns structured outputs such as recommended category, intent, confidence score, and prioritization signals. These results are written back to Dataverse under the same security boundary. Additional child flows execute asynchronously to evaluate SLA risk, determine priority, and apply routing recommendations, updating the case record accordingly.
When a response is required, a child flow invokes a second Copilot Studio action to generate a draft response. The agent retrieves only engagement specific historical cases, prior emails, and approved templates, and stores the drafted response along with evidence references in Dataverse. The AI does not send emails or take external actions.
GMS users review AI outputs and draft responses in the Dynamics 365 model driven app. Users can edit or override recommendations and must explicitly approve before sending any email. Throughout the lifecycle, Power Automate, Copilot Studio, and Dataverse generate comprehensive logs capturing AI decisions, confidence scores, overrides, approvals, and timestamps, ensuring full auditability and governance.


### Components

The logical architecture describes the end to end solution components and how they interact at a high level. Inbound emails are received in the engagement shared mailbox and ingested into Dynamics 365 Customer Service, where a case/activity record is created as the system-of-record entry point. A Power Automate cloud flow is triggered by case creation to orchestrate downstream processing. The flow persists normalized email content, metadata, and processing status into Microsoft Dataverse, and then invokes Microsoft Copilot Studio agent actions for AI reasoning (classification, prioritization, and response drafting). The Copilot agent reads only engagement-scoped records from Dataverse and writes back structured outputs (category, priority, confidence, draft text, evidence references). Finally, the D365 Model Driven UX surfaces these AI outputs to users for review, editing, approval, and case completion—ensuring the operational work remains within D365 while AI remains advisory and governed.
3.1.2	Sequence

 

                                                              Figure 2: Call Sequence
The sequence diagram explains the runtime behavior and order of execution. An external sender submits an email to the shared mailbox, after which D365 Customer Service ingests the message and creates a case. A Power Automate parent flow triggers on the case creation event, stamps/derives the engagement context, and stores the email record (and any extracted content) into Dataverse for traceability. The flow then calls a Copilot Studio agent action to perform email classification and intent detection, returning a category recommendation, confidence score, and routing/prioritization signals. Next, SLA logic is applied (commonly via a child flow) to compute SLA risk and update priority/escalation flags. If a response is required, the orchestration calls a second Copilot Studio action to generate a draft response using engagement-scoped history (similar cases/prior replies/templates), and stores the draft plus evidence references in Dataverse. The user then reviews the draft inside D365 (Model Driven App), edits if needed, and explicitly approves before sending. No email is ever sent autonomously by the agent; the final send and case status update are user driven, and all key actions are logged for audit.

3.1.3	Security and Boundary Access
Following diagram captures the mailbox agent security and boundary access
 
The security flow highlights how access is enforced end to end. Users authenticate into D365 and are authorized via role based access control (RBAC) to access mailbox cases and related records. Data access is further constrained using Dataverse row level security, ensuring users and services can only read/write records associated with their permitted engagement boundary (typically enforced through EngagementID and security roles/teams). Copilot Studio does not bypass these controls; instead, it accesses data only through scoped actions that query Dataverse under enforced permissions and engagement filters. As a result, the agent can only retrieve and reason over engagement scoped content, and all generated outputs (classification decisions, drafts, confidence scores, overrides) are written back into Dataverse under the same security constraints. This provides defense in depth: D365 RBAC governs who can access the experience, Dataverse row security governs what data can be accessed, and Copilot actions remain constrained to the same boundary, supporting compliance and audit expectations.


3.1.4	Infrastructure and Network components
 
Inbound & Case Creation
1.	External sender sends an email to the Exchange Online shared mailbox.
2.	Dynamics 365 Customer Service ingests the mailbox email and creates a Case (system of record).
Automation & Persistence
3.	A Power Automate cloud flow triggers on case creation.
4.	The flow stamps the EngagementID and persists email content and metadata into Dataverse with row-level security.
AI Classification & SLA Processing
5.	Power Automate invokes a Copilot Studio agent action for classification and intent detection.
6.	Copilot Studio reads only engagement-scoped records from Dataverse (RLS enforced).
7.	AI outputs (category, intent, confidence) are written back to Dataverse.
8.	Child flows compute SLA risk, priority, and routing recommendations.
Draft Response Generation
9.	When a response is required, Power Automate invokes a Draft Response agent action.
10.	Copilot retrieves historical cases, emails, and templates within the same EngagementID only.
11.	Draft response and evidence references are stored in Dataverse.
User Review & Approval
12.	The D365 Model-Driven App renders AI outputs and drafts.
13.	Dataverse ensures users see only permitted engagement data.
14.	GMS users review, edit, and approve drafts.
15.	Email sending is executed only by the user, never by AI.
Security, Identity & Audit
16.	Power Automate logs execution, overrides, and outcomes.
17.	Copilot Studio logs confidence scores and reasoning.
18.	Power Platform monitoring provides operational telemetry.
19.	Microsoft Entra ID governs authentication and authorization for all services.
3.1.5	Data Flows
 

The GMS Mailbox Agent data flow begins when an external sender submits an email to the GMS shared mailbox hosted in Exchange Online. Dynamics 365 Customer Service ingests the mailbox email using standard mailbox processing and creates or updates a Case, with the email stored as a related activity record. Dynamics 365 acts as the system of record for all mailbox interactions and case lifecycle management.
Case creation triggers a Power Automate parent orchestration flow. The flow reads the case and email content, derives the EngagementID, and persists normalized email metadata and extracted content into Microsoft Dataverse. Dataverse serves as the secure, auditable data layer, enforcing row level security to ensure all downstream processing is strictly scoped to the relevant engagement.
The orchestration then invokes a Copilot Studio agent action to perform AI assisted classification and intent detection. The agent reads only engagement scoped records from Dataverse and returns structured outputs such as recommended category, intent, confidence score, and prioritization signals. These results are written back to Dataverse under the same security boundary. Additional child flows execute asynchronously to evaluate SLA risk, determine priority, and apply routing recommendations, updating the case record accordingly.
When a response is required, a child flow invokes a second Copilot Studio action to generate a draft response. The agent retrieves only engagement specific historical cases, prior emails, and approved templates, and stores the drafted response along with evidence references in Dataverse. The AI does not send emails or take external actions.
GMS users review AI outputs and draft responses in the Dynamics 365 model driven app. Users can edit or override recommendations and must explicitly approve before sending any email. Throughout the lifecycle, Power Automate, Copilot Studio, and Dataverse generate comprehensive logs capturing AI decisions, confidence scores, overrides, approvals, and timestamps, ensuring full auditability and governance.



### Alternatives

-Azure Open AI Service provides foundational models and tools to build custom AI agents, but requires more development effort and does not offer the same level of turnkey integration with Power Automate and Dynamics 365 as Copilot Studio. Customers with existing investments in Azure OpenAI or specific customization needs may choose that path, but it will require building additional infrastructure for data access, security, and orchestration that Copilot Studio handles out of the box.
-Azure Open AI service could be used for using advance LLM models as per requirement
-Azure translation services could be used for translating email content if the use case requires multilingual support, but it would add complexity and cost compared to using a single AI agent that can handle multiple languages natively.
-Azure Document Intelligence could be used for advanced parsing of email attachments or complex content extraction, but for many mailbox automation scenarios, the built-in capabilities of Copilot Studio may be sufficient without needing a separate document processing service.



## Scenario details

Global Mobility Services (GMS) teams manage a high volume of operational activity across tax, immigration, and related service lines. Much of this activity is coordinated through engagement-specific shared mailboxes, which act as the primary channel for communication.
Engagement‑specific shared mailboxes are a core part of the operating model and are used to manage day‑to‑day communication throughout the lifecycle of an engagement. These mailboxes serve as a central point for receiving, responding to, and tracking engagement‑related correspondence.
Within the current operating model:
•	Email is a primary channel through which engagement activity is initiated, clarified, and progressed. 
•	Shared mailboxes are integrated with case management functionality, enabling emails to be associated with cases and tracked within existing platforms. 
•	Communication through the mailbox spans a wide range of interactions, including requests for information, status updates, clarifications, document exchanges, and confirmations.
The mailbox operates alongside other systems and tools used by GMS teams, such as case management platforms, workflow initiation tools, and shared repositories. The degree of reliance on these systems varies by service line, country, and engagement type.
GMS operations function within a highly regulated and distributed environment. This includes:
•	country specific data protection and data sovereignty requirements,
•	varying system access constraints across regions,
•	engagement level segregation of data and communications, and
•	the need to maintain traceability and accountability for client related correspondence.
Given this context, any capability that supports mailbox based work must operate within exist

*Solution why it was used*
Operationally, the end to end process begins when an email is received and ingested into D365, creating or updating a case. A Power Automate cloud flow triggers on case creation to persist email metadata/content to Dataverse, invoke Copilot Studio agent actions for classification and prioritization, then run SLA evaluation logic (commonly via child flows) to compute urgency and SLA risk. When a response is needed, a second agent action generates a draft reply using engagement scoped historical context (prior mailbox threads, similar cases, approved templates/rules), and the draft plus evidence references are stored back in Dataverse. Users review and approve the draft inside the D365 model driven experience; only after explicit approval is the reply sent—ensuring the agent never sends client emails autonomously
Security and compliance are enforced through defense in depth: users authenticate to D365 and are authorized via role based access control (RBAC), while Dataverse row level security enforces engagement boundaries (e.g., EngagementID scoping) for all data access. Copilot Studio does not bypass these controls; instead, the agent accesses data via scoped actions that retrieve only engagement permitted records and write back results under the same security constraints. This architecture provides strong auditability (classification decisions, confidence scores, overrides, SLA updates, draft approvals) and supports regulated operating requirements by ensuring the AI layer is governed, bounded, and human validated.

The logical architecture describes the end to end solution components and how they interact at a high level. Inbound emails are received in the engagement shared mailbox and ingested into Dynamics 365 Customer Service, where a case/activity record is created as the system-of-record entry point. A Power Automate cloud flow is triggered by case creation to orchestrate downstream processing. The flow persists normalized email content, metadata, and processing status into Microsoft Dataverse, and then invokes Microsoft Copilot Studio agent actions for AI reasoning (classification, prioritization, and response drafting). The Copilot agent reads only engagement-scoped records from Dataverse and writes back structured outputs (category, priority, confidence, draft text, evidence references). Finally, the D365 Model Driven UX surfaces these AI outputs to users for review, editing, approval, and case completion—ensuring the operational work remains within D365 while AI remains advisory and governed.
The sequence diagram explains the runtime behavior and order of execution. An external sender submits an email to the shared mailbox, after which D365 Customer Service ingests the message and creates a case. A Power Automate parent flow triggers on the case creation event, stamps/derives the engagement context, and stores the email record (and any extracted content) into Dataverse for traceability. The flow then calls a Copilot Studio agent action to perform email classification and intent detection, returning a category recommendation, confidence score, and routing/prioritization signals. Next, SLA logic is applied (commonly via a child flow) to compute SLA risk and update priority/escalation flags. If a response is required, the orchestration calls a second Copilot Studio action to generate a draft response using engagement-scoped history (similar cases/prior replies/templates), and stores the draft plus evidence references in Dataverse. The user then reviews the draft inside D365 (Model Driven App), edits if needed, and explicitly approves before sending. No email is ever sent autonomously by the agent; the final send and case status update are user driven, and all key actions are logged for audit.
The security flow highlights how access is enforced end to end. Users authenticate into D365 and are authorized via role based access control (RBAC) to access mailbox cases and related records. Data access is further constrained using Dataverse row level security, ensuring users and services can only read/write records associated with their permitted engagement boundary (typically enforced through EngagementID and security roles/teams). Copilot Studio does not bypass these controls; instead, it accesses data only through scoped actions that query Dataverse under enforced permissions and engagement filters. As a result, the agent can only retrieve and reason over engagement scoped content, and all generated outputs (classification decisions, drafts, confidence scores, overrides) are written back into Dataverse under the same security constraints. This provides defense in depth: D365 RBAC governs who can access the experience, Dataverse row security governs what data can be accessed, and Copilot actions remain constrained to the same boundary, supporting compliance and audit expectations.

Inbound & Case Creation
1.	External sender sends an email to the Exchange Online shared mailbox.
2.	Dynamics 365 Customer Service ingests the mailbox email and creates a Case (system of record).
Automation & Persistence
3.	A Power Automate cloud flow triggers on case creation.
4.	The flow stamps the EngagementID and persists email content and metadata into Dataverse with row-level security.
AI Classification & SLA Processing
5.	Power Automate invokes a Copilot Studio agent action for classification and intent detection.
6.	Copilot Studio reads only engagement-scoped records from Dataverse (RLS enforced).
7.	AI outputs (category, intent, confidence) are written back to Dataverse.
8.	Child flows compute SLA risk, priority, and routing recommendations.
Draft Response Generation
9.	When a response is required, Power Automate invokes a Draft Response agent action.
10.	Copilot retrieves historical cases, emails, and templates within the same EngagementID only.
11.	Draft response and evidence references are stored in Dataverse.
User Review & Approval
12.	The D365 Model-Driven App renders AI outputs and drafts.
13.	Dataverse ensures users see only permitted engagement data.
14.	GMS users review, edit, and approve drafts.
15.	Email sending is executed only by the user, never by AI.
Security, Identity & Audit
16.	Power Automate logs execution, overrides, and outcomes.
17.	Copilot Studio logs confidence scores and reasoning.
18.	Power Platform monitoring provides operational telemetry.
19.	Microsoft Entra ID governs authentication and authorization for all services.


## Issues and considerations

Manual shared mailbox management for GMS team is inefficient due to: 
•	Engagement mailboxes receive a very high volume of emails daily, with some regions handling several hundred emails per day. Most of these emails require human interpretation to determine whether action is required, what type of action is needed, and who should own it. 
•	The current D365 mailbox setup relies primarily on keyword‑based rules to categorise emails and assign them to workstreams or users. Keyword rules are not mutually exclusive, causing frequent misallocation and rework. Overlapping categories (e.g., tax vs immigration, billing vs general queries) are common and cannot be reliably resolved through static rules. When categorisation fails, emails are routed to common or default queues, requiring manual reassignment.
•	SLA risks are not proactively surfaced. Users rely on manual review to detect urgency, dissatisfaction, or escalation tone.
•	Teams repeatedly respond to similar queries without an easy way to view prior responses or communication history within the same mailbox.
•	Lack of visibility into mailbox activity and communication patterns, i.e., volume of emails exchanged per case, internal vs external communication volumes, as well as the repeated follow-ups with specified local offices or parties.


### Potential use cases

*Billing file generation for Tax and Legal*
*New Assignment Initiation for Global mobility services*
*AI asssited case assignment, classification, resolution etc*

## Considerations

•	≥ 70% of emails auto-categorized correctly in MVP.
•	≥ 40% improvement in SLA management by effective prioritization. 
•	≥ 40% reduction in manual triage effort (measured in hours). 
•	≥ 20% improvement in user satisfaction with mailbox management (measured through surveys).


### Security

Inbound & Case Creation
1.	External sender sends an email to the Exchange Online shared mailbox.
2.	Dynamics 365 Customer Service ingests the mailbox email and creates a Case (system of record).
Automation & Persistence
3.	A Power Automate cloud flow triggers on case creation.
4.	The flow stamps the EngagementID and persists email content and metadata into Dataverse with row-level security.
AI Classification & SLA Processing
5.	Power Automate invokes a Copilot Studio agent action for classification and intent detection.
6.	Copilot Studio reads only engagement-scoped records from Dataverse (RLS enforced).
7.	AI outputs (category, intent, confidence) are written back to Dataverse.
8.	Child flows compute SLA risk, priority, and routing recommendations.
Draft Response Generation
9.	When a response is required, Power Automate invokes a Draft Response agent action.
10.	Copilot retrieves historical cases, emails, and templates within the same EngagementID only.
11.	Draft response and evidence references are stored in Dataverse.
User Review & Approval
12.	The D365 Model-Driven App renders AI outputs and drafts.
13.	Dataverse ensures users see only permitted engagement data.
14.	GMS users review, edit, and approve drafts.
15.	Email sending is executed only by the user, never by AI.
Security, Identity & Audit
16.	Power Automate logs execution, overrides, and outcomes.
17.	Copilot Studio logs confidence scores and reasoning.
18.	Power Platform monitoring provides operational telemetry.
19.	Microsoft Entra ID governs authentication and authorization for all services.



### Cost optimization
Cost item	Quantity	Unit	Unit price	Monthly cost	Notes / Calculation
API Management (APIM)	1	unit	150.01	150.01	Base monthly price per selected tier; excludes overage requests.
Azure Functions (Premium EP1)	2190	instance-hours	0.084	183.96	If Function Plan is Premium EP1: min instances * hours * env count.
Azure Functions (Consumption executions)	0	million exec	0.2	0	If Consumption: executions/1M * env count. Free grant excluded.
Azure Functions (Consumption GB-s)	0	GB-s	0.000016	0	If Consumption: executions * sec * GB * env count. Free GB-s grant excluded.
Blob Storage (Hot LRS capacity)	1500	GB-month	0.018	27	Storage capacity cost only; transactions/egress not included.
Private Endpoints (endpoint-hours)	4380	endpoint-hours	0.01	43.8	count * hours * env count.
Private Endpoints (data processed)	600	GB	0.01	6	Data processed through Private Endpoints; tiered rates not modeled.
App Gateway (gateway-hours)	2190	hours	0.045	98.55	If enabled: hours * env count.
Azure Bastion (hourly)	0	hours	0.19	0	If enabled: hours * env count. Only Basic priced; add other SKUs if needed.
Azure Monitor / Log Analytics (ingestion)	30	GB	2.3	69	Monthly log ingestion cost (Analytics). Retention/export not modeled.
TOTAL (Estimated) - Azure (A)				578.32	Sum of modeled monthly costs.
					
Power Platform ( Per user plan)	150	per user license	15	2250	Assuming 150 live users having per user plan licensing in Power platform. Some of them would already be having licensing . So no extra cost. Here the cost assumes 150 new live users 
TOTAL (Estimated) - Power Platform(B)				2250	
					
TOTAL (A+B)				2828.32	


### Operational excellence

Application Lifecycle Management (ALM)
Application lifecycle management is a structured process to manage an application from idea to retirement. It maintains a controlled and a governed way for application planning, build , test, deployment, operation and improvement.
For agents built on copilot studio, ALM is very essential as it ensures – structured dev, control deployment, governance and security, version control, safe rollback strategy. These are the main pillars for proper ALM setup for copilot
 
Environment Strategy

An environment is a separate bucket which hosts all the components required for a copilot studio agent – topics, flows, connections etc. Separate environments need to be provisioned in the power platform tenant first. This can be done by an user who is a power platform admin or 0365 admin. Please navigate to Power Platform admin center to provision environment.
 
The table below drafts the purpose of each environment and key stakeholders
Environment	Purpose	Solution Type to be present	Key Stakeholders
Dev	Build agents and unit test agents	Unmanaged	Developers
Test	QA Validation	Managed	QA
UAT	UAT Validation	Managed	UAT testers, super users, business users
Prod	Live production agent	Managed	Live users

Key principles:
1.	All dev should be done in a separate solution. A publisher prefix needs to be created and all components of a copilot studio agent like topics, triggers, flows, connection references needs to be present in the same solution. This avoids dependency issues while moving components across environments during CI/CD pipeline runs. Never should any component of any copilot studio agent be created in the default solution of the environment
2.	No edit to any agent component should be directly done in the target environment like Test/UAT/Prod. This creates an unmanaged layer in the target and changes do not reflect when pipelines move components 
3.	Always managed solution should be used to deploy to Test, UAT and Prod. This would ensure changes are sync to dev and any changes move through pipelines on an approved path
Solution Strategy
Copilot studio components must live always inside a power platform solution. This ensures all the necessary components used to build the agent can be successfully moved across to higher environments when CI/CD pipelines are set up in DEVOPS.
The components for a copilot studio agent which gets created in the backend are typically:
•	Topics
•	Entities
•	Plugins
•	Power automate flows
•	Connection references
•	Environment variables
•	Custom connectors
This is critical because if  some of the components resides outside the solution( may be in default solution) we get cross dependencies or circular dependency issues in deploying to high environments.
Dev to Deploy Strategy

DEV(Build) Process

1.	Create publisher first in the power platform dev environment
2.	Create a separate unmanaged solution using the publisher. Give proper description and versioning of the solution(major.minor.build.revision)
3.	Go to copilot studio and use the solution created above as the preferred solution
4.	Build the agent – topics, flows etc in copilot studio. Power platform would automatically add the components build in the copilot studio into this solution
5.	Configure environment variables wherever required with out hardcoding them. These include API URLs, service endpoints, SharePoint sites etc
6.	In agent flows use connection references instead of connections. This avoids hardcoding of the dataverse connections
Deployment Process(CI/CD Pipelines)
A proper deployment process should use:
•	Azure devops repo for solution control and versioning
•	Used managed deployment process
•	Enviornment variables configuration in power platform to avoid hardcoding URLS, 
•	Connection reference binding

Prerequisites
•	Enviornment strategy need to be aligned with the Dev.QA,UAT and Prod environments already provisioned
•	Solution setup in Dev must be completed. Dev should have an unmanaged solution into which all copilot studio agents components should sit under.
•	Service principals needs to be created with power platform and dataverse access given in EntraID App registration
•	Create separate service connections in Azure devops using the client idf and secrets generated from Entra ID app registration. 
•	Install Power platform build tools devops extension in the Azure Devops Organization
Process
1.	Create a CI pipeline. Following would be the steps that a CI pipeline typically would do:
•	Export unmanaged solution created above
•	Unpack to source control (Devops repo)
•	Version increment
•	Pack managed solution to be deployed through CD pipeline
•	Publish artifacts
Pseudo code for a CI YAML pipeline:
trigger:
- main

pool:
  vmImage: 'windows-latest'

variables:
  SolutionName: 'YourCopilotSolution'
  DevServiceConnection: 'PP-DEV-SPN'
  ArtifactName: 'drop'

steps:
# 1) Install Power Platform Build Tools (must be first)
- task: microsoft-IsvExpTools.PowerPlatform-BuildTools.tool-installer.PowerPlatformToolInstaller@2
  displayName: 'Power Platform Tool Installer'
  inputs:
    AddToolsToPath: true
# Tool Installer requirement + YAML snippet is documented by Microsoft. [2](https://learn.microsoft.com/en-us/power-platform/alm/devops-build-tool-tasks)

# 2) (Optional) Verify connectivity early (WhoAmI)
# Microsoft notes WhoAmI can be used to verify connection early. [2](https://learn.microsoft.com/en-us/power-platform/alm/devops-build-tool-tasks)

# 3) Export solution from DEV
- task: PowerPlatformExportSolution@2
  displayName: 'Export solution (unmanaged) from DEV'
  inputs:
    authenticationType: 'PowerPlatformSPN'
    PowerPlatformSPN: '$(DevServiceConnection)'
    SolutionName: '$(SolutionName)'
    SolutionOutputFile: '$(Build.ArtifactStagingDirectory)\$(SolutionName)_unmanaged.zip'
    Managed: false

# 4) (Optional) Run Solution Checker / static analysis
# Build Tools support static analysis checks using Power Apps checker service. [1](https://learn.microsoft.com/en-us/power-platform/alm/devops-build-tools)[7](https://marketplace.visualstudio.com/items?itemName=microsoft-IsvExpTools.PowerPlatform-BuildTools)

# 5) Publish artifact
- publish: '$(Build.ArtifactStagingDirectory)'
  artifact: '$(ArtifactName)'

2.	Create a CD(Release Pipeline). 
Pseudo code for CD release pipeline
The steps followed in a release pipeline are as below:

trigger: none

pool:
  vmImage: 'windows-latest'

resources:
  pipelines:
  - pipeline: build
    source: Your-Build-Pipeline-Name
    trigger: true

variables:
  SolutionName: 'YourCopilotSolution'
  UatServiceConnection: 'PP-UAT-SPN'
  ProdServiceConnection: 'PP-PROD-SPN'

stages:
- stage: Deploy_UAT
  displayName: 'Deploy to UAT'
  jobs:
  - job: ImportUAT
    steps:
    - task: microsoft-IsvExpTools.PowerPlatform-BuildTools.tool-installer.PowerPlatformToolInstaller@2
      displayName: 'Power Platform Tool Installer'
      inputs:
        AddToolsToPath: true
    # Tool Installer requirement is documented by Microsoft. [2](https://learn.microsoft.com/en-us/power-platform/alm/devops-build-tool-tasks)

    - download: build
      artifact: drop

    - task: PowerPlatformImportSolution@2
      displayName: 'Import solution into UAT'
      inputs:
        authenticationType: 'PowerPlatformSPN'
        PowerPlatformSPN: '$(UatServiceConnection)'
        SolutionInputFile: '$(Pipeline.Workspace)\build\drop\$(SolutionName)_unmanaged.zip'
        AsyncOperation: true

- stage: Deploy_PROD
  displayName: 'Deploy to PROD'
  dependsOn: Deploy_UAT
  # Add an Environment with approvals in Azure DevOps UI for PROD stage gating (recommended).
  jobs:
  - job: ImportPROD
    steps:
    - task: microsoft-IsvExpTools.PowerPlatform-BuildTools.tool-installer.PowerPlatformToolInstaller@2
      displayName: 'Power Platform Tool Installer'
      inputs:
        AddToolsToPath: true

    - download: build
      artifact: drop

    - task: PowerPlatformImportSolution@2
      displayName: 'Import solution into PROD'
      inputs:
        authenticationType: 'PowerPlatformSPN'
        PowerPlatformSPN: '$(ProdServiceConnection)'
        SolutionInputFile: '$(Pipeline.Workspace)\build\drop\$(SolutionName)_unmanaged.zip'
        AsyncOperation: true

``

Post Deployment Steps
•	Configure environment variables in the target environment 
•	Connection references bind to existing connections
Governance Controls and Rollback Strategy
•	Stage gating controls need to be inplace in the ALM setup with approvals required by QA before UAT deployment and UAT users/super users/business users/product manager approval before Prod deployment
•	Version incremental logic needs to be handled in pipeline with Devops repo being the source of truth and pipelines extracting and checking in the components into repo everytime
•	Artifacts retention needs to be done in case rollback needs to be done to a previous version. If artifacts are retained in repo rollback to a previous managed version can be done
Governance Framework
Governance on copilot studio agents should cover 4 major pillars like
•	Security and Access control
•	Data protection and compliance
•	Generative AI answers governance
•	Operational Monitoring

Security and Access control
Role separation and responsibilities of each role is the starting point of security and access control. In copilot studio agent dev-> deployment lifecycle there are typically some key stakeholders whose role and access needs to be properly defined and aligned. These are as below:
Role	Responsibility
Copilot maker	Build topics, triggers, flows, connections etc
PP Admin	Control environments
Devops engineer	CI/CD pipelines build, monitoring failures etc
Business owner	Approvals 

The security and access control would work in conjunction with:
•	Microsoft Entra Id
•	Microsoft Power Platform
•	Microsoft Copilot studio
These are the three security layers which work together to control what an agent can see and do in copilot studio
   


Step By Step process 
1.	User logs in – This gets authenticated through entra Id( Layer 1 is involved)
2.	User belongs to different security groups created in entra id like copilot-makers-dev, copilot-users-prod etc
3.	When creating an environment – dev,test,uat a specific security group is assigned. This ensures that only members of that security group in entra id can access that environment
4.	Inside each environment security roles to users must be assigned. This ensures what a particular user can do inside that environment. Copilot studio run on top of the dataverse security access layer which restricts them to access certain tables, flows, connections etc if there security role does not permit them to do that
DLP Policies
DLP policies are configured at the tenant and the environment level by admins which restricts users/agents to do certain operations in that environment like :
•	accessing non-business connectors for business data, 
•	use HTTP connections in Prod etc
Data protection and Compliance
For AI agents data controls are essential. Control needs to be in place for:
•	Restrict data sources for generative answers
•	Validate sharepoint and website indexing
•	Prevent exposure to sensitive dataverse tables
•	Classify data sources
•	Enable auditing
Generative AI Governance

Generative AI introduces dynamic responses. So governance need to be in place. Some of the key governance for generative answers are as below:
•	Prompt designs need to be reviewed
•	Index sources need to be reviewed
•	Security need to be reviewed before prod deployment
•	Monitoring of conversation transcripts
•	Identify hallucinations
•	Tracking of inaccurate responses
•	Testing of generative answers in dev
Operational Monitoring
Copilot studio dashboards helps in monitoring key performance metrics
Some of the Key metrics to track for operational monitoring are:
•	Escalation rate
•	Failure rate 
•	Fallback triggers
•	User feedback score



## Contributors


**Principal authors:**

- [Saphalya Mohanty](https://www.linkedin.com/in/saphalya-mohanty-b3826458?utm_source=share_via&utm_content=profile&utm_medium=member_android ) | (Solutions Director, KPMG(KDNI))



*Include additional links to Dynamics 365 or Power Platform guidance, or Azure Architecture Center articles. Here is an example:*

See the following related architecture guides and solutions:

- [Artificial intelligence (AI) - Architectural overview](https://learn.microsoft.com/azure/architecture/data-guide/big-data/ai-overview)
- [Choosing a Microsoft cognitive services technology](https://learn.microsoft.com/azure/architecture/data-guide/technology-choices/cognitive-services)
- [Chatbot for hotel reservations](https://learn.microsoft.com/azure/architecture/example-scenario/ai/commerce-chatbot)
- [Build an enterprise-grade conversational bot](https://learn.microsoft.com/azure/architecture/reference-architectures/ai/conversational-bot)
- [Speech-to-text conversion](https://learn.microsoft.com/azure/architecture/reference-architectures/ai/speech-ai-ingestion)  
