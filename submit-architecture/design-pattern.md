

# Article title


The GMS Mailbox Agent is an agent first, D365 native capability designed to help Global Mobility Services teams manage high volume engagement mailboxes by improving email classification, SLA aware prioritization, routing recommendations, and response drafting—while ensuring mandatory human review before any client communication is sent. The solution uses Dynamics 365 Customer Service as the system of record for case creation and lifecycle management, with Microsoft Dataverse providing a secure and auditable data layer for engagement scoped email content, AI outputs, and operational logs. Microsoft Copilot Studio acts as the reasoning layer (classification/prioritization/drafting), and Power Automate provides reliable event driven orchestration and guaranteed processing—ensuring the agent augments operations without replacing governance or control


## Context and problem

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
Given this context, any capability that supports mailbox based work must operate within existing platforms, respect engagement boundaries, and align with established governance and compliance requirements.


## Solution

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


Consider the following points when deciding how to implement this pattern:

- Automated email classification and prioritization using LLM's
- Text based key word rules lead to wrong assignment of cases. Also, text based rules cannot extract attachment content to do auto-classification. AI builder text extracts models through Power automate and LLM prompts are used for these
- AI scans through email content, subject, attachments to prioritize the case. Escalations are clearly handled without overshooting the SLA commitments

## When to use this pattern

The GMS Mailbox Agent data flow begins when an external sender submits an email to the GMS shared mailbox hosted in Exchange Online. Dynamics 365 Customer Service ingests the mailbox email using standard mailbox processing and creates or updates a Case, with the email stored as a related activity record. Dynamics 365 acts as the system of record for all mailbox interactions and case lifecycle management.
Case creation triggers a Power Automate parent orchestration flow. The flow reads the case and email content, derives the EngagementID, and persists normalized email metadata and extracted content into Microsoft Dataverse. Dataverse serves as the secure, auditable data layer, enforcing row level security to ensure all downstream processing is strictly scoped to the relevant engagement.
The orchestration then invokes a Copilot Studio agent action to perform AI assisted classification and intent detection. The agent reads only engagement scoped records from Dataverse and returns structured outputs such as recommended category, intent, confidence score, and prioritization signals. These results are written back to Dataverse under the same security boundary. Additional child flows execute asynchronously to evaluate SLA risk, determine priority, and apply routing recommendations, updating the case record accordingly.
When a response is required, a child flow invokes a second Copilot Studio action to generate a draft response. The agent retrieves only engagement specific historical cases, prior emails, and approved templates, and stores the drafted response along with evidence references in Dataverse. The AI does not send emails or take external actions.
GMS users review AI outputs and draft responses in the Dynamics 365 model driven app. Users can edit or override recommendations and must explicitly approve before sending any email. Throughout the lifecycle, Power Automate, Copilot Studio, and Dataverse generate comprehensive logs capturing AI decisions, confidence scores, overrides, approvals, and timestamps, ensuring full auditability and governance.
 to help the reader determine if the solution is applicable to their specific scenario.*

Use this pattern when:

•	AI‑assisted email classification and categorization is required
•	Ownership assignment using classification logic and business routing rules.
•	Email prioritization based on nature and tone of the email.
•	Ability to scan mailbox to surface previous responses sent to the same sender, prior correspondence related to the same employee, and similar past cases within the same engagement mailbox.
•	Draft response generation using templates, mailbox history, and business rules, with mandatory human 


This pattern might not be suitable:

- Huge volumes of transaction emails comes to the mailbox. It might lead to throttling with requests overshooting Datverse web api limits
- Multilingual processing. Auto response cannot be drafted in other languages. That would require language translation API's on Azure cognitive services and is out of scope for the current implementation
- Saving emails outside of Datverse in country specific document storage

## Example

4.2	Power Automate Design
1.	Parent Orchestration Flow (Build First)
Trigger
•	When a D365 Case is created from mailbox ingestion
Steps
•	Read Case + Email
•	Stamp EngagementID
•	Persist MailboxEmail record
•	Invoke Copilot Studio Action (classification)
•	Set ProcessingStatus = “AI Evaluated”
•	Fire child flows asynchronously
Child Flow – Classification
•	Text extraction
•	AI classification
•	Update case fields
Child Flow: SLA Management
•	 Recompute priority 
•	Escalation checks
Child Flow: Routing Enforcement
Logic
•	Read agent recommendation
•	Assign queue / user
•	Capture overrides
Child Flow: Draft Generation
Triggers only when needed to prepare a draft response
4.3	Copilot Studio Agent Design
4.3.1	Agent Responsibilities
The Copilot Studio agent is responsible for:
•	Interpreting inbound email intent
•	Classifying emails into engagement specific categories
•	Detecting urgency, SLA risk, and escalation tone
•	Retrieving similar past cases and responses
•	Drafting context aware email responses
•	Answering ad hoc user questions (Release 2)
The agent will not:
•	Send emails autonomously
•	Cross engagement boundaries
•	Bypass D365 security controls
4.3.2	Agent Skills Breakdown
4.3.2.1	Skill1: AI-Assisted Breakdown
Inputs: Subject, body, attachment text, metadata 
Outputs: 
•	Category
•	Intent
•	Confidence score
 Behavior: 
•	AI overrides keyword rules
•	Low confidence flags case for review
4.3.2.2	Skill2: SLA Risk Detection
This prompt would be identifying for SLA risk based on the input
Evaluates: 
•	Time since receipt
•	Engagement SLA profile
•	Sentiment analysis
Output: Priority recommendation
4.3.2.3	Skill3: Draft Responses
•	Skill 3: Historical Context Retrieval
•	Searches: 
o	Prior emails from same sender
o	Past cases for same employee
o	Similar resolved cases
•	Scope: Same EngagementID only
•	Skill 4: Draft Response Generation
•	Uses: 
o	Approved templates
o	Mailbox conversation history
o	Business rules
•	Output includes: 
o	Draft body
o	Referenced evidence (case IDs, message IDs)
4.3.3	AI Agent Prompts
4.3.3.1	Copilot Agent System prompt
For compliance we would need a prompt. Example of it:
PROMPT
You are the GMS Mailbox Agent.

Your role is to support Global Mobility Services (GMS) users in managing engagement-specific shared mailboxes within Microsoft Dynamics 365.

CRITICAL RULES (NON-NEGOTIABLE):
1. You may ONLY use data that belongs to the provided EngagementID.
2. You must NEVER reference, infer, or use information from:
   - Other engagements
   - Other clients
   - Other countries
   - Other mailboxes
3. You must not fabricate information.
4. You must provide a confidence score for every recommendation you make.
5. If confidence is below the defined threshold, you MUST explicitly request human review.
6. You must NEVER send emails or take external actions autonomously.
7. All outputs must be suitable for audit and compliance review.

You operate exclusively within approved Dynamics 365 and Dataverse data sources scoped by EngagementID.


4.3.3.2	Email Classification and Intent Prompt
This is the email classification prompt to be used inside the child flow.
PROMPT
Task: Classify the inbound email and determine its primary intent.

Context:
- EngagementID: {EngagementID}
- Email Subject: {Subject}
- Email Body: {BodyExtract}
- Sender: {Sender}
- Attachments (text extracted if available): {AttachmentText}

Instructions:
1. Determine the most appropriate category from the allowed engagement-specific categories.
2. Identify the primary intent of the email (e.g. assignment query, billing query, document request, status update, general enquiry).
3. Consider overlapping categories carefully and select the single best classification.
4. Provide a numeric confidence score (0–100).
5. If confidence is below 70, flag the classification for human review.

Return output in the following structured format:

Category:
Intent:
ConfidenceScore:
ReviewRequired (Yes/No):
Reasoning (concise, factual, non-speculative):


4.3.3.3	SLA Risk Prompt
PROMPT
Task: Evaluate whether this case is at risk of breaching SLA and recommend priority.

Context:
- EngagementID: {EngagementID}
- CaseID: {CaseID}
- Received DateTime: {ReceivedDateTime}
- SLA Profile: {SLAProfileDetails}
- Email Content: {BodyExtract}
- Prior Email Count from Same Sender: {FollowUpCount}

Instructions:
1. Assess urgency based on language cues, deadlines, dissatisfaction, or escalation tone.
2. Consider elapsed time against SLA thresholds.
3. Recommend one priority level (Low / Medium / High / Critical).
4. Provide confidence score and clear reasoning.
5. If uncertainty exists, recommend escalation for review.

Return output in the following format:

RecommendedPriority:
SLARisk (Low/Medium/High):
ConfidenceScore:
EscalationSuggested (Yes/No):
Reasoning:


4.3.3.4	Similar Case Prompt
PROMPT
Task: Retrieve relevant historical engagement-specific context to support classification and response drafting.

Context:
- EngagementID: {EngagementID}
- Current CaseID: {CaseID}
- Sender Email Address: {Sender}
- Related Employee Identifier (if available): {EmployeeID}

Instructions:
1. Identify similar past cases within the same EngagementID only.
2. Identify prior email conversations with the same sender within this engagement.
3. Highlight previously used responses that resolved similar queries.
4. Do NOT summarize or use data from outside this engagement.

Return output in the following format:

SimilarCases:
- CaseID: 
  Summary:
  ResolutionType:

RelevantPriorEmails:
- EmailDate:
  Summary:

ReusableResponsePatterns (if any):



4.3.3.5	Draft Response Generation Prompt
PROMPT
Task: Generate a draft email response for human review.

Context:
- EngagementID: {EngagementID}
- Current Email: {BodyExtract}
- Similar Cases Summary: {SimilarCaseSummary}
- Approved Templates: {ApprovedTemplates}
- Business Rules: {BusinessRules}

Instructions:
1. Draft a professional, clear, and concise email response.
2. Align tone with Global Mobility Services standards.
3. Reuse approved wording where appropriate.
4. Reference relevant case history internally using evidence links.
5. DO NOT assume facts not present in the engagement data.
6. DO NOT send or imply sending the email.

Return output in this format:

DraftResponse:
EvidenceReferences:
- CaseID:
- EmailID(s):
ConfidenceScore:
HumanReviewRequired (Always = Yes):



## Contributors

<!--(This section is optional if all the contributors would prefer to not include it)-->

*This article is maintained by Microsoft. It was originally written by the following contributors.*

Principal author:

- [Saphalya Mohanty](https://www.linkedin.com/in/saphalya-mohanty-b3826458?utm_source=share_via&utm_content=profile&utm_medium=member_android ) | Solutions Director, KPMG (KDN-I)
