---
title: Enterprise call center architecture on Dynamics 365 Customer Service for Health Care Domain
description: Generalized reference architecture for an enterprise call center using Dynamics 365 Customer Service, Omnichannel, portals, and an extensible Azure integration layer.
keywords: Dynamics 365, Customer Service, Omnichannel, call center, reference architecture, portals, Dataverse, integration, Azure, APIM, Logic Apps, Functions
ms.service: dynamics-365
ms.subservice: guidance
ms.topic: conceptual
ms.custom: bap-template
author: RahulDubey2207
ms.date: 03/24/2026
---

# Enterprise call center architecture on Dynamics 365 Customer Service

This generalized architecture pattern shows how to build an enterprise-scale call center solution using Dynamics 365 Customer Service and Omnichannel, with secure self-service portals and an extensible Azure integration layer. It helps solution architects design scalable, reliable, secure, and cost-aware customer service platforms for regulated industries such as healthcare.

This solution is a generalized architecture pattern, which can be used for many different scenarios and industries. See the following example solutions that build off of this core architecture:
- [Member and provider self-service for regulated customer service](https://learn.microsoft.com/dynamics365/guidance/placeholder)
- [Enterprise integration blueprint for Dynamics 365 Customer Service](https://learn.microsoft.com/dynamics365/guidance/placeholder)

## Architecture

> **Architecture diagram goes here** (insert your image or a diagram export).

Download a [PowerPoint file](https://github.com/microsoft/dynamics365patternspractices/) with this architecture. <!-- Change the link to point to your PowerPoint file -->

### Dataflow

1. A member or provider signs up and authenticates through Azure Active Directory (or another identity configuration aligned to enterprise identity strategy) and accesses the relevant portal (Member Portal or Provider Portal).
2. The external user creates a case or checks case status from the portal. The portal writes the case data into Microsoft Dataverse (Dynamics 365 Customer Service).
3. Call center agents and supervisors access the unified case workstream in Dynamics 365 Customer Service, including customer profile context, case history, activities, and timelines.
4. Omnichannel routes incoming digital interactions (chat, email, and voice) to the correct queue based on routing rules, skill/availability, and priority.
5. Dynamics 365 applies case management automation using business process flows, routing rules, SLAs, and workflows to maintain consistent handling and escalation.
6. Agents collaborate using integrated productivity tools (for example, email handling via Exchange and document storage in SharePoint) while maintaining a single case record of truth.
7. Knowledge articles are used to standardize resolution guidance and improve first-contact resolution.
8. Where enterprise integrations are required (for example, external ticketing or downstream systems), the Azure integration layer provides decoupled orchestration:
   - Azure API Management secures and publishes APIs.
   - Logic Apps orchestrate business workflows.
   - Azure Functions implement event-driven processing and transformation.
   - Azure Monitor captures telemetry, logging, and alerting.
9. Operational insights are surfaced via dashboards and reporting for service management and continuous improvement.

### Components

- [Dynamics 365 Customer Service](https://learn.microsoft.com/dynamics365/customer-service/overview)  
  Core case management, SLAs, queues, routing rules, dashboards, and audit/activities.
- [Omnichannel for Customer Service](https://learn.microsoft.com/dynamics365/customer-service/omnichannel/overview)  
  Unified agent experience across chat, voice, and digital channels with intelligent routing and agent workspace.
- [Microsoft Dataverse](https://learn.microsoft.com/power-apps/maker/data-platform/data-platform-intro)  
  Data platform for customer profile, cases, activities, and supporting entities with role-based security.
- [Power Pages](https://learn.microsoft.com/power-pages/introduction) (or equivalent portal capability)  
  Member and provider portals for self-service case creation and status tracking.
- [Microsoft Entra ID (Azure Active Directory)](https://learn.microsoft.com/entra/fundamentals/what-is-entra)  
  Central identity and access management for internal users (and external identities depending on the chosen model).
- [SharePoint](https://learn.microsoft.com/sharepoint/introduction)  
  Document management and controlled access to case-related artifacts.
- [Exchange Online](https://learn.microsoft.com/microsoft-365/enterprise/exchange-online)  
  Email channel integration for case communications and notifications.
- [Azure API Management](https://learn.microsoft.com/azure/api-management/api-management-key-concepts)  
  API gateway for security, throttling, versioning, and governance.
- [Azure Logic Apps](https://learn.microsoft.com/azure/logic-apps/logic-apps-overview)  
  Workflow orchestration for integrations and business processes.
- [Azure Functions](https://learn.microsoft.com/azure/azure-functions/functions-overview)  
  Serverless compute for transformations, event handlers, and lightweight services.
- [Azure Monitor](https://learn.microsoft.com/azure/azure-monitor/overview)  
  Observability, metrics, logs, and alerting across the end-to-end solution.

### Alternatives

The following alternative solutions provide scenario-focused lenses to build off of this core architecture:
- [Industry lens: Healthcare member services contact center](https://learn.microsoft.com/dynamics365/guidance/placeholder)
- [Industry lens: Financial services customer care contact center](https://learn.microsoft.com/dynamics365/guidance/placeholder)

Alternative technologies to consider depending on constraints and enterprise standards:
- **Integration pattern choices**
  - Use event streaming (for example, Azure Event Grid or Service Bus) when you need higher decoupling, buffering, or guaranteed delivery patterns for downstream systems.
  - Use synchronous APIs for real-time UI needs, and asynchronous orchestration for back-office updates to protect agent experience.
- **Voice and telephony**
  - Consider certified telephony integrations when existing telephony platforms must be retained or when regulatory requirements mandate specific call recording or retention mechanisms.
- **Identity for external users**
  - If external identities require social logins, federation, or advanced customer identity controls, evaluate an external identity provider strategy aligned to enterprise security policies.

## Scenario details

Enterprise call centers in regulated industries must support high-volume interactions while meeting strict security, compliance, and audit requirements. This scenario provides a scalable approach to unify case management, routing, and omni-channel engagement on Dynamics 365 Customer Service.

Common challenges addressed by this scenario include:
- Fragmented customer data and case histories across channels
- Manual triage and inconsistent routing leading to SLA breaches
- Limited visibility into end-to-end interaction history
- Difficulty extending to external systems without increasing platform coupling
- Requirement for auditable changes and secure external access for members and providers

This generalized architecture pattern demonstrates how to:
- Centralize customer and case data on Dataverse with role-based access controls
- Use Omnichannel to provide consistent agent experiences across chat, email, and voice
- Enable self-service via portals to reduce call volume and improve transparency
- Introduce an Azure-based integration layer to decouple external systems and improve resiliency

### Potential use cases

This architecture pattern applies to many customer service scenarios, including:
- **Healthcare**: member services, provider support, eligibility inquiries, and benefits administration
- **Finance**: customer care for banking/insurance, claims or dispute handling, and regulated servicing workflows
- **Government**: citizen services, permit inquiries, service requests, and contact center modernization
- **Telecommunications and utilities**: service requests, billing issues, outage reporting, and retention operations

## Considerations

These considerations help implement a solution that includes Dynamics 365. Learn more at [Dynamics 365 guidance documentation](https://learn.microsoft.com/dynamics365/guidance/).

### Reliability

Reliability ensures your application can meet the commitments you make to your customers. For more information, see [Overview of the reliability pillar](https://learn.microsoft.com/azure/architecture/framework/resiliency/overview).

Key reliability design considerations shows up in three places: channel workloads (Omnichannel), core case processing (Dataverse + D365), and integrations (Azure layer).

**Recommended practices**
- **Protect the agent experience with asynchronous integration**
  - Offload long-running and failure-prone downstream updates to Logic Apps/Functions (or messaging-based patterns) rather than blocking agent operations.
  - Use retry policies with exponential backoff in integration workflows and ensure idempotency (safe reprocessing).
- **Design for partial failure**
  - If an external ticketing system is unavailable, allow cases to continue within Dynamics 365 and reconcile later using queued integration.
  - Provide user-visible status indicators (for example, “sync pending”) rather than hard failures.
- **High availability and resilience**
  - Use Azure Monitor alerts for core signals: queue backlog, integration failures, channel availability, and Dataverse API throttling.
  - Build operational runbooks for common reliability incidents: channel degradation, integration outage, portal sign-in issues.
- **Data integrity and recovery**
  - Apply environment strategy (DEV/TEST/PROD) and controlled deployments (ALM pipelines) to reduce configuration drift.
  - Use solution segmentation (core vs integration vs portal) to isolate failures and simplify rollback.

**What to measure**
- SLA attainment and breach rates
- Average and percentile handle time by channel
- Queue backlog and routing latency
- Integration error rate, retry count, and time-to-recovery (MTTR)

### Security

Security provides assurances against deliberate attacks and the abuse of your valuable data and systems. For more information, see [Overview of the security pillar](https://learn.microsoft.com/azure/architecture/framework/security/overview).

**Recommended practices**
- **Identity and access**
  - Use Entra ID for internal users and align external user access to enterprise identity governance.
  - Enforce least privilege with role-based security in Dynamics 365 and Dataverse.
- **Data protection**
  - Apply field-level security for sensitive attributes and ensure portal users can only access their own records via table permissions.
  - Store documents in SharePoint with controlled permissions rather than in Dataverse for large file needs.
- **API governance**
  - Place API Management in front of integrations to enforce authentication, throttling, IP filtering (as needed), and versioning.
- **Baseline security**
  - Follow Azure Security Baselines for Azure services used in the integration layer and standardize configuration via policy/blueprints.
  - Centralize logs and alerts in Azure Monitor to detect suspicious patterns or abuse.

### Cost optimization

Cost optimization is about looking at ways to reduce unnecessary expenses and improve operational efficiencies. For more information, see [Overview of the cost optimization pillar](https://learn.microsoft.com/azure/architecture/framework/cost/overview).

This architecture can be cost-effective when you scale the right components for the right workload and avoid unnecessary platform consumption.

**Primary cost drivers**
- Omnichannel capacity and concurrent workload levels (chat/voice)
- Dataverse storage (data and file storage) and API consumption
- Integration services usage (Logic Apps/Functions executions, APIM calls)
- Monitoring and logging volume (Azure Monitor ingestion)

**Recommended cost controls**
- **Reduce Dataverse storage pressure**
  - Store documents and large attachments in SharePoint rather than Dataverse file columns where appropriate.
  - Define data retention policies for non-essential audit/interaction logs and archive analytical datasets outside transactional storage.
- **Prefer asynchronous processing**
  - Use Logic Apps/Functions for downstream tasks rather than heavy synchronous plug-ins that increase platform consumption and risk timeouts.
- **Right-size Omnichannel and channels**
  - Enable channels based on business demand and phase rollout (email/chat first, voice next) to avoid overprovisioning.
  - Use forecasting to align staffing and concurrency to business peaks.
- **Govern telemetry costs**
  - Keep high-cardinality logs under control; log what you need for incident resolution and compliance, and set retention appropriately.

**How scale affects costs**
- Increased case volume typically scales Dataverse API and storage usage.
- Increased concurrent interactions drive Omnichannel usage and routing/agent workload requirements.
- Increased integration volume scales API calls and workflow executions.

**Pricing estimation**
Use the Azure pricing calculator to estimate Azure layer costs (API Management, Logic Apps, Functions, Monitor) along with expected call volume and retention settings:
- https://azure.microsoft.com/pricing/calculator/

> Note: Costs vary significantly based on concurrency, retention, and the number of integrations. Consider modeling small/medium/large usage tiers based on daily case volume and peak concurrent interactions.

### Operational excellence

Operational excellence covers the operations processes that deploy an application and keep it running in production. For more information, see [Overview of the operational excellence pillar](https://learn.microsoft.com/azure/architecture/framework/devops/overview).

**Recommended practices**
- Implement ALM with managed solutions, automated deployments, and environment segregation.
- Standardize monitoring dashboards across Dynamics 365 and Azure (channel health, integration health, and platform throttling).
- Create runbooks for common issues: routing misconfiguration, channel incidents, portal authentication problems, and integration failures.
- Use release rings (pilot → phased rollout) for high-impact routing or SLA changes to reduce operational risk.

### Performance efficiency

Performance efficiency is the ability of your workload to scale to meet the demands placed on it by users in an efficient manner. For more information, see [Performance efficiency pillar overview](https://learn.microsoft.com/azure/architecture/framework/scalability/overview).

**Recommended practices**
- Avoid heavy synchronous plug-ins on critical user flows (case create/update, routing events). Use asynchronous designs for downstream processing.
- Keep routing logic maintainable and measurable; periodically tune queues, skills, and routing rules based on operational analytics.
- Optimize portal queries and data exposure by limiting retrieved fields and enforcing strict filtering and permissions.
- Use API Management throttling and caching patterns where appropriate to protect backend services during spikes.

## Deploy this scenario

A typical deployment approach:
1. Establish environments (DEV/TEST/UAT/PROD) and ALM pipelines.
2. Implement core data model, security roles, and case management baseline (queues, SLAs, routing).
3. Configure Omnichannel channels incrementally and validate routing at scale.
4. Implement portals with table permissions, authentication, and scoped data access.
5. Introduce Azure integration layer for external systems with API Management, orchestration, and monitoring.
6. Conduct performance and reliability validation (load tests for concurrency and integration failure simulations).
7. Roll out via phased releases and operationalize monitoring, runbooks, and continuous improvement.

## Contributors

*This article is maintained by Microsoft. It was originally written by the following contributors.*

**Principal authors:**
- [Rahul Dubey](http://linkedin.com/ProfileURL) \
 (Business Process Architecture Manager)

> [!TIP]
> To see non-public LinkedIn profiles, sign in to LinkedIn.

## Next steps

- [Dynamics 365 guidance documentation](https://learn.microsoft.com/dynamics365/guidance/)
- [Dynamics 365 Customer Service documentation](https://learn.microsoft.com/dynamics365/customer-service/)
- [Omnichannel for Customer Service documentation](https://learn.microsoft.com/dynamics365/customer-service/omnichannel/)
- [Power Pages documentation](https://learn.microsoft.com/power-pages/)
- [Microsoft Dataverse documentation](https://learn.microsoft.com/power-apps/maker/data-platform/)
- [Azure API Management documentation](https://learn.microsoft.com/azure/api-management/)
- [Azure Logic Apps documentation](https://learn.microsoft.com/azure/logic-apps/)
- [Azure Functions documentation](https://learn.microsoft.com/azure/azure-functions/)
- [Azure Monitor documentation](https://learn.microsoft.com/azure/azure-monitor/)

## Related resources

This solution is a generalized architecture pattern, which can be used for many different scenarios and industries. See the following example solutions that build off of this core architecture:
- [Link to first solution idea or other architecture that builds off this solution](https://learn.microsoft.com/dynamics365/guidance/placeholder)
- [Second solution idea that builds off this solution](https://learn.microsoft.com/dynamics365/guidance/placeholder)

See the following related architecture guides and solutions:
- [Azure Architecture Center](https://learn.microsoft.com/azure/architecture/)
- [Microsoft Cloud Adoption Framework](https://learn.microsoft.com/azure/cloud-adoption-framework/)