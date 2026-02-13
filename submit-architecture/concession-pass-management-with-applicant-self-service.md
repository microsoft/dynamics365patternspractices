---
title: Concession pass management with applicant self-service  
description: Sample architecture for concession pass management combining applicant self‑service, Dynamics 365 case and order processing, and Azure‑based integrations.
keywords: concession pass management, applicant self-service, Dynamics 365, Power Platform, Power Pages, case management, order processing.
ms.service: dynamics-365 #Required. Leave as-is for all things Dynamics 365, but change to dccp for DCCP content.
ms.subservice: guidance #Required. Leave as-is.
ms.topic: conceptual #Required. Leave as-is.
ms.custom: bap-template #Required; Leave as-is.
author: Aish-SA #Required; your GitHub user alias, with correct capitalization. 
ms.date: 02/16/2023
---
# Concession pass management with applicant self-service

This solution architecture describes an end‑to‑end approach to concession pass management with applicant self‑service, combining a digital portal experience with backend case management and order processing. Applicants can apply for concession passes, upload supporting information, track application status, and request renewals or replacements through a secure self‑service channel, while operational teams manage eligibility checks, cases, payments, fulfilment, and exceptions through a centralized service management experience. The solution demonstrates how low‑code workflows, integrated data, and backend automation can be orchestrated to deliver a scalable, secure, and maintainable concession pass lifecycle, improving both customer experience and operational efficiency.

## Architecture
*Architecture diagram goes here. Under the architecture diagram, include this sentence and a link to the Visio file or the PowerPoint file:*
This architecture enables a Concession Pass Provider to deliver a modern, secure, and supportable concession pass management capability using **Microsoft Dynamics 365 Customer Service and Sales on Microsoft Dataverse**, extended through **Power Platform** capabilities. Applicant self service is delivered via **Power Pages**, with **SharePoint Online** supporting secure document management. **Azure Logic Apps and Azure Functions** orchestrate integrations with external validation, payment, fulfilment, and hot listing services, enabling a scalable, loosely coupled, and resilient architecture.
Download a [PowerPoint file](https://github.com/microsoft/dynamics365patternspractices/) with this architecture.<!-- Change the link to point to your PowerPoint file>

### Workflow
*An alternate title for this sub-section is "Workflow" (if data isn't really involved).*
*In this section, include a numbered list that annotates/describes the dataflow or workflow through the solution. Explain what each step does. Start from the user or external data source, and then follow the flow through the rest of the solution (as shown in the diagram).*
#### 1. Applicant Management
<br> This workflow ensures applicant information and supporting proofs are captured, validated, and approved before any concession pass activity is allowed. </br>
-	Applicant details are captured via the portal or by staff in D365 CRM.
-	Supporting proofs are uploaded and linked to the applicant record.
-	Automated validations check completeness and data formats.
-	Staff perform manual verification where required.
-	Applicant status is updated to indicate eligibility or required follow up.

#### 2. Concession Pass Application & Pass History
<br> This workflow manages the creation and processing of concession pass applications using orders in D365 CRM, while maintaining full pass history visibility. </br>
-	Application is initiated by the applicant (portal) or staff (CRM).
-	A pass order is created and linked to the applicant record.
-	Eligibility and business rules are evaluated.
-	Application progresses through review and approval stages.
-	Approved passes are recorded and pass history is made available to applicants and staff.
#### 3. Case Management
<br> This workflow enables structured capture, routing, and resolution of applicant enquiries, feedback, and complaints. </br>
- A case is created via the portal or CRM.
- Case is categorised and automatically routed to the correct team.
- Staff investigate, communicate, and record actions.
- Case status is updated throughout its lifecycle.
- Case is resolved, closed, and retained for audit and reporting.
#### 4. Data Synchronisation
<br> This workflow keeps reference data in Dataverse aligned with the source data stored in Azure SQL DB. </br>
- Reference data changes are identified in Azure SQL DB.
- Scheduled synchronisation retrieves updated records.
- Data is validated and mapped to Dataverse entities.
- Records are created or updated in Dataverse.
- Processing status and errors are logged.
#### 5. Replacement and Hot listing
<br> This workflow manages pass replacement scenarios while ensuring existing passes are invalidated appropriately. </br>
- Replacement request is submitted via portal or CRM.
- A replacement order is created and linked to the existing pass.
- Replacement rules are validated.
- Existing pass is hot listed and marked inactive.
- Replacement pass progresses to fulfilment.
#### 6. Payment Management
<br> This workflow supports secure payment processing for chargeable pass scenarios without storing sensitive payment data. </br>
- Payment is initiated from the portal or CRM.
- A secure payment session is launched.
- Payment outcome is returned to the system.
- Order is updated with success or failure status.
- Successful payments allow the process to continue.
#### 7. Pass Product and Fulfilment
<br> This workflow manages the final production and issuance of concession passes once all validations and approvals are complete. </br>
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
*Use this section to talk about alternative Azure services or architectures that you might consider for this solution. Include the reasons why you might choose these alternatives. Customers find this valuable because they want to know what other services or technologies they can use as part of this architecture.*
*What alternative technologies were considered and why didn't we use them?*
*List all "children" architectures (likely solution ideas) that build off this GAP architecture*
The following alternative solutions provide scenario-focused lenses to build off of this core architecture:  
- [Link to first solution idea or other architecture that builds off this solution](filepath.md)
- [Second solution idea that builds off this solution](filepath.md)
  
## Scenario details
Public‑sector and regulated service providers often operate high‑volume, multi‑channel concession pass services using manual or fragmented processes, leading to long processing times, limited visibility, and inconsistent customer experiences. These services typically depend on multiple internal systems and external parties—such as validation, fulfilment, payments, and hot‑listing—introducing integration complexity and increasing the risk of manual handling and slow resolution.

This architecture demonstrates a unified, digital‑first approach that modernizes concession pass management by enabling applicant self‑service, automating validation and fulfilment workflows, and centralizing incident, case, and pass or order lifecycles. Dynamics 365 Power Apps and Microsoft Dataverse act as the system of record, while Azure‑based integrations standardize interactions with external services to improve reliability, consistency, and operational efficiency.

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
Operational excellence covers the operations processes that deploy an application and keep it running in production. Learn more at [Process-focused solution](https://learn.microsoft.com/dynamics365/fasttrack/implementation-guide/process-focused-solution) and [Overview of the operational excellence pillar](https://learn.microsoft.com/azure/architecture/framework/devops/overview).This is enabled through end‑to‑end observability, automation‑first operations, controlled lifecycle management, and low‑code maintainability, supporting reliable operations and continuous improvement.

## Deploy this scenario
This sample architecture can be deployed using standard Microsoft Power Platform and Dynamics 365 environment strategies. To run this scenario in production, organizations should configure separate environments for development, testing, and production; apply role‑based security and data access controls; and integrate with required external services such as validation, fulfilment, payment, and hot‑listing providers.

To deploy this scenario, organizations should configure Microsoft Entra ID for secure access, enable SharePoint Online for document storage, and provision Azure Functions and Logic Apps for external integrations. Production deployments can adjust security, integrations, and scaling based on operational and regulatory needs.

## Contributors
*(Expected, but this section is optional if all the contributors would prefer to not include it)*
*Start with the explanation text (same for every section), in italics. This makes it clear that Microsoft takes responsibility for the article (not the one contributor). Then include the "Pricipal authors" list and the "Additional contributors" list (if there are additional contributors). Link each contributor's name to the person's LinkedIn profile. After the name, place a pipe symbol ("|") with spaces, and then enter the person's title. We don't include the person's company, MVP status, or links to additional profiles (to minimize edits/updates). (The profiles can be linked to from the person's LinkedIn page, and we hope to automate that on the platform in the future). Implement this format with the explanation text formatted in italics:*
*This article is maintained by Microsoft. It was originally written by the following contributors.*
**Principal authors:**
- [Aishwarya Ramani](http://linkedin.com/ProfileURL) | (Title, such as "Principal Consultant")

## Next steps
*Link to Learn articles, along with any third-party documentation.*
*Where should I go next if I want to start building this?*
*Are there any relevant case studies or customers doing something similar?*
*Is there any other documentation that might be useful? Are there product documents that go into more detail on specific technologies that are not already linked?*
Examples:
- [Azure Kubernetes Service (AKS) documentation](https://learn.microsoft.com/azure/aks)
- [Azure Machine Learning documentation](https://learn.microsoft.com/azure/machine-learning)
- [What are Azure Cognitive Services?](https://learn.microsoft.com/azure/cognitive-services/what-are-cognitive-services)
- [What is Language Understanding (LUIS)?](https://learn.microsoft.com/azure/cognitive-services/luis/what-is-luis)
- [What is the Speech service?](https://learn.microsoft.com/azure/cognitive-services/speech-service/overview)
- [What is Azure Active Directory B2C?](https://learn.microsoft.com/azure/active-directory-b2c/overview)
- [Introduction to Bot Framework Composer](https://learn.microsoft.com/composer/introduction)
- [What is Application Insights](https://learn.microsoft.com/azure/azure-monitor/app/app-insights-overview)
## Related resources
*Use "Related resources" for architecture information that's relevant to the current article. Lead this section with links to the solution ideas that connect back to this architecture.*
This solution is a generalized architecture pattern, which can be used for many different scenarios and industries. See the following example solutions that build off of this core architecture:
- [Link to first solution idea or other architecture that builds off this solution](https://learn.microsoft.com/dynamics365/guidance/placeholder)
- [Second solution idea that builds off this solution](https://learn.microsoft.com/dynamics365/guidance/placeholder)
*Include additional links to Dynamics 365 or Power Platform guidance, or Azure Architecture Center articles. Here is an example:*
See the following related architecture guides and solutions:
- [Artificial intelligence (AI) - Architectural overview](https://learn.microsoft.com/azure/architecture/data-guide/big-data/ai-overview)
- [Choosing a Microsoft cognitive services technology](https://learn.microsoft.com/azure/architecture/data-guide/technology-choices/cognitive-services)
- [Chatbot for hotel reservations](https://learn.microsoft.com/azure/architecture/example-scenario/ai/commerce-chatbot)
- [Build an enterprise-grade conversational bot](https://learn.microsoft.com/azure/architecture/reference-architectures/ai/conversational-bot)
- [Speech-to-text conversion](https://learn.microsoft.com/azure/architecture/reference-architectures/ai/speech-ai-ingestion)
