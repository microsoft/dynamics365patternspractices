---
title: Concession pass management with applicant self-service  
description: Sample architecture for concession pass management combining applicant self‑service, Dynamics 365 case and order processing, and Azure‑based integrations.
keywords: concession pass management, applicant self-service, Dynamics 365, Power Platform, Power Pages, case management, order processing, local authority, public sector, government, transport authority.
ms.service: dynamics-365 #Required. Leave as-is for all things Dynamics 365, but change to dccp for DCCP content.
ms.subservice: guidance #Required. Leave as-is.
ms.topic: conceptual #Required. Leave as-is.
ms.custom: bap-template #Required; Leave as-is.
author: Aish-SA #Required; your GitHub user alias, with correct capitalization. 
ms.date: 02/16/2026
---
# Concession pass management with applicant self-service

This solution architecture enables end‑to‑end concession pass management by combining applicant self‑service with centralized case management and order processing. A secure digital portal supports applications, evidence submission, status tracking, and renewals, while backend automation and low‑code workflows deliver a scalable, secure, and operationally efficient concession pass lifecycle.

## Architecture
![Architecture diagram](https://raw.githubusercontent.com/Aish-SA/dynamics365patternspractices/main/architectures/Concession-pass-management-solution-architecture.jpg)

<br> Download a [Visio file](https://raw.githubusercontent.com/Aish-SA/dynamics365patternspractices/main/architectures/Concession-pass-management-solution-architecture.vsdx) with this architecture.</br>

### Workflow
#### 1. Applicant Management
This workflow ensures applicant information and supporting proofs are captured, validated, and approved before any concession pass activity is allowed.
-	Applicant details are captured via the portal or by staff in D365 CRM.
-	Supporting proofs are uploaded and linked to the applicant record.
-	Automated validations check completeness and data formats.
-	Staff perform manual verification where required.
-	Applicant status is updated to indicate eligibility or required follow up.
#### 2. Concession Pass Application & Pass History
This workflow manages the creation and processing of concession pass applications using orders in D365 CRM, while maintaining full pass history visibility. 
-	Application is initiated by the applicant (portal) or staff (CRM).
-	A pass order is created and linked to the applicant record.
-	Eligibility and business rules are evaluated.
-	Application progresses through review and approval stages.
-	Approved passes are recorded and pass history is made available to applicants and staff.
-	Existing passes are scheduled to be auto renewed upon expiry.
#### 3. Case Management
This workflow enables structured capture, routing, and resolution of applicant enquiries, feedback, and complaints. 
- A case is created via the portal or CRM.
- Case is categorised and automatically routed to the correct team.
- Staff investigate, communicate, and record actions.
- Case status is updated throughout its lifecycle.
- Case is resolved, closed, and retained for audit and reporting.
#### 4. Data Synchronisation
This workflow keeps reference data in Dataverse aligned with the source data stored in Azure SQL DB. 
- Reference data changes are identified in Azure SQL DB.
- Scheduled synchronisation retrieves updated records.
- Data is validated and mapped to Dataverse entities.
- Records are created or updated in Dataverse.
- Processing status and errors are logged.
#### 5. Replacement and Hot listing
This workflow manages pass replacement scenarios while ensuring existing passes are invalidated appropriately. 
- Replacement request is submitted via portal or CRM.
- A replacement order is created and linked to the existing pass.
- Replacement rules are validated.
- Existing pass is hot listed and marked inactive.
- Replacement pass progresses to fulfilment.
#### 6. Payment Management
This workflow supports secure payment processing for chargeable pass scenarios without storing sensitive payment data. 
- Payment is initiated from the portal or CRM.
- A secure payment session is launched.
- Payment outcome is returned to the system.
- Order is updated with success or failure status.
- Successful payments allow the process to continue.
#### 7. Pass Production and Fulfilment
This workflow manages the final production and issuance of concession passes once all validations and approvals are complete. 
- Approved orders are identified for fulfilment.
- Pass production data is prepared.
- Pass is produced and issued.
- Issued pass details are stored in Dataverse.
- Applicant can view fulfilment status and issued pass details.

### Components
- [Power Pages](https://learn.microsoft.com/power-pages/): Provides a secure, externally accessible portal for applicants to submit and manage concession pass requests.
- [Dynamics 365 Customer Service](https://learn.microsoft.com/dynamics365/customer-service/): Supports case management to record feedback and complaints as incidents, route them to the appropriate teams, and manage each case through a defined lifecycle and status model.
- [Dynamics 365 Sales](https://learn.microsoft.com/dynamics365/sales/): Manages order creation and processing associated with concession pass issuance and renewals.
- [Microsoft Dataverse](https://learn.microsoft.com/power-platform/architecture/products/microsoft-dataverse): Acts as the central data platform, storing application, case, order, and audit data securely.
- [Power Automate](https://learn.microsoft.com/power-automate/): A low code workflow service used to orchestrate business processes across the platform, including applicant validation, application progression, notifications, renewals, managing payments, supporting underlying integrations and scheduled jobs.
- [Azure Functions](https://learn.microsoft.com/azure/azure-functions/functions-overview): Implements serverless, event-driven logic for fulfilment, batch processing, and custom integrations.
- [Azure Logic Apps](https://learn.microsoft.com/azure/logic-apps/logic-apps-overview): Orchestrates system-to-system integrations with external services in a loosely coupled manner, complementing Power Automate for more integration centric use cases.
- [SharePoint Online](https://learn.microsoft.com/sharepoint/): Provides secure document storage and lifecycle management for uploaded proofs and supporting evidence.
- [Microsoft Entra ID](https://learn.microsoft.com/entra/fundamentals/what-is-entra/): A cloud based identity and access management service that secures access for both applicants and internal users across the portal and CRM applications. It provides authentication, authorisation, and policy enforcement, enabling secure sign in experiences and centralised identity management aligned with modern security practices.
- [Azure DevOps](https://learn.microsoft.com/azure/devops/user-guide/what-is-azure-devops): A lifecycle management platform used for source control, work item tracking, and automated deployment pipelines for the solution components. Azure DevOps supports controlled, repeatable deployments across environments and enables governance, traceability, and collaboration throughout the delivery lifecycle

### Alternatives
The following alternative solutions provide scenario-focused lenses to build off of this core architecture:  
- **Intelligent document processing with AI Builder:**
AI Builder can be introduced to process physical or scanned application forms and supporting documents, enabling automated data extraction, validation, and classification. This supports hybrid digital journeys where applicants submit paper forms, while still benefiting from automated backend processing and reduced manual data entry.
- **Conversational self‑service using Power Virtual Agents (Copilot Studio):**
Power Virtual Agents can be embedded within the applicant portal to provide conversational self‑service, answering common queries, guiding users through application steps, and surfacing application status or eligibility information. This can reduce contact centre demand while improving accessibility and user experience.
- **Advanced analytics and operational insights:**
The solution can be extended with Power BI or Microsoft Fabric to deliver richer operational dashboards, including application throughput, eligibility outcomes, exception trends, and fulfilment performance, supporting data‑driven service improvement.
- **Proactive communications and notifications:**
Event‑driven automation can be expanded to deliver proactive notifications (for example, renewal reminders or missing evidence prompts) across multiple channels, improving completion rates and reducing avoidable follow‑ups.
- **Fraud detection and anomaly identification:**
Additional Azure or Power Platform AI capabilities can be layered in to identify unusual patterns in applications, renewals, or replacements, supporting fraud prevention and safeguarding controls.

These enhancements can be adopted selectively and incrementally, allowing organisations to start with a robust core concession pass management capability and evolve toward more intelligent, automated, and user‑centric services over time.
  
## Scenario details
The Concession Pass Provider operates high-volume, multi-channel concession pass services that require secure customer engagement, consistent eligibility decisions, accurate reference data, dependable fulfilment, and resilient operations. 

In addition, concessionary pass services depend on multiple external parties (e.g., fulfilment, validation, hot-listing, payments) and internal data sources, which creates integration complexity and increases the risk of manual handling, inconsistent data, and slow resolution cycles.

This architecture demonstrates a unified, digital‑first approach that modernizes concession pass management by enabling applicant self‑service, automating validation and fulfilment workflows, and centralizing incident and pass order lifecycles. Dynamics 365 Power Apps and Microsoft Dataverse act as the system of record, while Azure‑based integrations standardize interactions with external services to improve reliability, consistency, and operational efficiency.

### Potential use cases
This solution is well suited for government, transportation authorities, education providers, and other regulated sectors that manage eligibility-based passes, permits, or entitlements requiring supporting evidence and fulfilment.

## Considerations
These considerations help implement a solution that includes Dynamics 365 and reflects on the Success by Design framework and the Well-Architected Framework (WAF) pillars. Learn more at [Dynamics 365 guidance documentation](https://learn.microsoft.com/dynamics365/guidance/).
### Environment strategy
Environments are containers that store, manage, and share your organization's data. They also store the data model, application metadata, process definitions, and the security constructs to control access to data and apps. Learn more at [Environment strategy](https://learn.microsoft.com/dynamics365/fasttrack/implementation-guide/environment-strategy).
Separate environments should be used for development, testing, and production to support controlled deployment, validation, and operational stability.
### Data management
Data governance, architecture, modeling, storage, migration, integration, and quality can help you make informed decisions, improve your customer engagement, and gather real-time information about your products in the field. Learn more at [Data management](https://learn.microsoft.com/dynamics365/fasttrack/implementation-guide/data-management).  
Dataverse provides a secure and auditable data layer, while SharePoint Online helps optimize storage for large files and unstructured content.
### Application lifecycle management
End-to-end lifecycle management can provide improved visibility, automation, delivery, and future planning for a Dynamics 365 solution. Learn more at [Application lifecycle management](https://learn.microsoft.com/dynamics365/fasttrack/implementation-guide/application-lifecycle-management). 
Solution packaging, environment variables, and automated deployment pipelines help ensure consistency and reduce deployment risk.
### Performance efficiency
Performance and early prioritization are directly related to the success of a project. Learn more at [A performing solution, beyond infrastructure](https://learn.microsoft.com/dynamics365/fasttrack/implementation-guide/performing-solution).  
Asynchronous processing and serverless integrations enable the solution to scale with demand while maintaining responsive user experiences.
### Security
Security provides assurances against deliberate attacks and the abuse of your valuable data and systems. Learn more at [Overview of the security pillar](https://learn.microsoft.com/azure/architecture/framework/security/overview) and [Security in Dynamics 365 implementations](https://learn.microsoft.com/dynamics365/fasttrack/implementation-guide/security).
Role-based access, identity management, and secure integration patterns help protect sensitive applicant data and support compliance requirements.
### Cost optimization
Cost optimization is about looking at ways to reduce unnecessary expenses and improve operational efficiencies. Learn more at [Overview of the cost optimization pillar](https://learn.microsoft.com/azure/architecture/framework/cost/overview).
Using low-code services and serverless compute helps align costs with usage and minimizes the need for custom infrastructure.
### Operational excellence
Operational excellence covers the operations processes that deploy an application and keep it running in production. Learn more at [Process-focused solution](https://learn.microsoft.com/dynamics365/fasttrack/implementation-guide/process-focused-solution) and [Overview of the operational excellence pillar](https://learn.microsoft.com/azure/architecture/framework/devops/overview). This is enabled through end‑to‑end observability, automation‑first operations, controlled lifecycle management, and low‑code maintainability, supporting reliable operations and continuous improvement.

## Deploy this scenario
This sample architecture can be deployed using standard Microsoft Power Platform and Dynamics 365 environment strategies. To run this scenario in production, organizations should configure separate environments for development, testing, and production; apply role‑based security and data access controls; and integrate with required external services such as validation, fulfilment, payment, and hot‑listing providers.

To deploy this scenario, organizations should configure Microsoft Entra ID for secure access, enable SharePoint Online for document storage, and provision Azure Functions and Logic Apps for external integrations. Production deployments can adjust security, integrations, and scaling based on operational and regulatory needs.

## Contributors
*This article is maintained by Microsoft. It was originally written by the following contributors.*

<br> Principal author: </br>
- [Aishwarya Ramani](http://www.linkedin.com/in/aishwarya-ramani-11340062) | Principal Consultant

> [!TIP]
> To see non-public LinkedIn profiles, sign in to LinkedIn.

## Next steps
To continue exploring this architecture and begin implementation, review the following product and platform guidance.
- Learn how to build secure external-facing portals using [Power Pages](https://learn.microsoft.com/en-us/power-pages/) and [Microsoft Entra External ID](https://learn.microsoft.com/en-us/power-pages/security/authentication/entra-external-id).
- Explore case management capabilities in [Customer Service](https://learn.microsoft.com/en-us/dynamics365/customer-service/) for managing applications, incidents, and exceptions.
- Understand how Dynamics 365 [Sales](https://learn.microsoft.com/en-us/dynamics365/sales/) order processing can be used to manage application fulfilment, issuance, and lifecycle tracking.
- Explore Azure integration and automation capabilities using [Azure Logic Apps](https://learn.microsoft.com/en-us/azure/logic-apps/).
- Learn how to extend workflows with custom, event-driven logic using [Azure Functions](https://learn.microsoft.com/en-us/azure/azure-functions/).

## Related resources
The following resources provide architectural context and solution ideas that align with or extend this concession pass management architecture:
- [Microsoft Power Platform and Copilot Studio Architecture Center](https://learn.microsoft.com/en-us/power-platform/architecture/)
- [Power Platform Well-Architected guidance](https://learn.microsoft.com/en-us/power-platform/architecture/architecture-center-overview)
- [Power Platform reference architectures](https://learn.microsoft.com/en-us/power-platform/architecture/reference-architectures/)
