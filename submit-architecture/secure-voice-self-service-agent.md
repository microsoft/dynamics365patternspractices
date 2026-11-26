---
title: Build a secure voice self-service agent with the Customer Conversation harness and Contact Center Intelligence
description: Learn how to build a Copilot Studio voice and chat agent that verifies callers with voice biometrics, acts on Dataverse records through agent flows, and hands off to a contact center representative.
#customer intent: As a Power Platform architect, I want to learn how to build a customer-facing voice agent that verifies the caller, changes account data safely, and keeps representatives and internal teams informed, so that I can automate routine contact center requests without losing security or context.
ms.date: 11/26/2026
ms.topic: example-scenario
ms.subservice: architecture-center
author: magdalena-kaczkowska
ms.author: 
ms.reviewer: 
---

# Build a secure voice self-service agent with the Customer Conversation harness and Contact Center Intelligence

Customers often call a contact center for routine account changes, such as checking, starting, changing, or cancelling a subscription. Each of these calls needs the same steps: identify the caller, confirm their identity, make the change in the system of record, document it, confirm it to the customer, and hand over to a person when needed. This reference architecture shows how to build a customer-facing agent in Microsoft Copilot Studio that runs on the Customer Conversation harness, verifies callers with voice biometrics from Microsoft Contact Center Intelligence (CCI), performs account changes through agent flows in Microsoft Dataverse, and keeps both the representative and internal teams informed.

The example implementation is a subscription service. The same pattern applies to any scenario where a caller must be verified before the agent reads or changes their data, for example utilities, telecommunications, insurance, or retail loyalty programs.

> [!TIP]
> This article provides an example scenario and a visual representation of a secure voice self-service agent built with Copilot Studio. This solution is a generalized example architecture that you can adapt to many scenarios and industries.

## Architecture

:::image type="content" source="media/secure-voice-self-service-agent/architecture.png" alt-text="Architecture diagram that shows callers reaching a Copilot Studio agent through Azure Communication Services, Dynamics 365 Contact Center, Teams Phone, and web chat. The agent uses Contact Center Intelligence voice biometrics, agent flows, Dataverse, Outlook, and Microsoft Teams." lightbox="media/secure-voice-self-service-agent/architecture.png":::

*Download an [SVG file](media/secure-voice-self-service-agent/architecture.svg) of this architecture.*

## Workflow

The numbers and letters match the labels in the diagram.

1. **Call**: The customer calls a toll-free number provided by Azure Communication Services. The caller can speak or use the phone keypad (DTMF).

1. **Inbound call to the workstream**: Azure Communication Services delivers the call to a voice workstream in Dynamics 365 Contact Center, which handles queuing and routing.

1. **Handoff to the AI agent**: The voice workstream has the Copilot Studio agent assigned as its AI agent, so the agent answers the call first. A fallback queue takes the call if the agent isn't available. The agent uses the Customer Conversation harness, which is built for customer-facing voice and chat conversations.

   **A. Teams Phone**: Employees can call the same agent through a Teams Phone resource account of type AI agent. This path reaches the agent directly, without the contact center queue.

   **C. Web chat**: Customers can also use the agent in a website chat. In chat, voice biometrics isn't available, so the agent verifies the customer with customer number and PIN.

1. **Speech**: Microsoft-managed speech services convert audio to text and text to speech, so the same agent logic serves voice and chat.

1. **Voice biometrics**: The agent asks for the customer number, then sends a speech sample and the caller ID to the biometric authentication in Contact Center Intelligence. The result is *Verified*, *NotVerified*, or *FraudDetected*.
   - *Verified*: An agent flow records the verification for this conversation.
   - *NotVerified* or not available: The agent asks for a four-digit PIN, spoken or typed on the keypad. A voice sample is enrolled only after a successful PIN verification and with the customer's consent.
   - *FraudDetected*: The agent tells the customer clearly that the voice didn't pass the security check, makes no changes, and hands off to a representative with a warning in the summary.

   The agent always tells the customer the verification result in plain words (positive or negative), so the customer knows why the next step happens.

1. **Agent flows as tools**: The primary agent handles verification and wrap-up. It delegates domain work to three sub-agents: subscription information, new subscription, and subscription changes and cancellation. Each sub-agent calls its own agent flows, such as *Get subscriptions*, *Get plan catalog*, *Create subscription*, *Update subscription*, and *Cancel subscription*.

1. **Dataverse**: Agent flows read and write Dataverse tables through a connection reference. Every flow that changes data first checks on the server side that the contact was verified in the current conversation and that the verification hasn't expired. After each change, the flow writes a timeline note, creates a case for a representative, and stores a copy of the confirmation email.

1. **Customer email**: Outlook sends the customer a confirmation email for every change. The email has **Confirm** and **Undo** links. Each link opens a confirmation page that changes nothing on its own. Only when the customer selects the button on that page does the *Email response* flow validate the single-use token from the link and confirm or reverse the change. The team receives a copy. For details, see [Protect action links](#security).

1. **Representative and app changes**: Representatives in the Copilot Service workspace see the case, notes, and emails that the agent created. When a representative changes a subscription status directly in the app, a Dataverse-triggered flow sends the customer the same kind of email with Confirm and Undo.

1. **Escalation**: When the customer asks for a person, when the request is out of scope, or when the voice check returns *FraudDetected*, the agent hands the conversation to a representative in Dynamics 365 Contact Center with a summary.

1. **Team notifications**: Two notification flows post adaptive cards to Microsoft Teams:
   - A subscription feed posts every new, restored, or cancelled subscription to the subscription team's channels, with the source (agent or representative).
   - A security alert flow posts to the security team's channel when the voice check returns *FraudDetected*, when verification is locked, or after three failed PIN attempts. It also writes a note on the contact's timeline. The customer doesn't receive an email, so a possible impersonator gets no warning.

   **B. Testing (planned)**: The Copilot Studio Kit can run test sets against the agent through a Direct Line token endpoint.

## Components

[**Azure Communication Services**](/azure/communication-services/): Provides the toll-free phone number and connects public switched telephone network (PSTN) calls to Dynamics 365 Contact Center.

[**Dynamics 365 Contact Center**](/dynamics365/contact-center/): Handles the voice workstream, queuing, routing, and the handoff between the AI agent and representatives. Representatives work in the Copilot Service workspace.

[**Microsoft Copilot Studio**](/microsoft-copilot-studio/): Hosts the primary agent and its sub-agents on the Customer Conversation harness. Topics handle deterministic steps such as verification and wrap-up, and generative orchestration handles intent recognition and routing to sub-agents.

**Microsoft Contact Center Intelligence**: Provides voice biometric authentication, voiceprint management, and fraud detection that the agent uses during the call.

**Teams Phone**: A resource account of type AI agent lets employees call the agent from Microsoft Teams.

[**Power Automate agent flows**](/microsoft-copilot-studio/): Run the deterministic business logic as tools that the agents call: verification, data changes, notes, cases, emails, and notifications. Dataverse-triggered cloud flows react to changes made outside the agent.

[**Microsoft Dataverse**](/power-apps/maker/data-platform/data-platform-intro): Stores contacts with verification fields, subscriptions, cases, notes, emails, and conversation records written by Contact Center.

**Office 365 Outlook**: Sends confirmation emails with Confirm and Undo buttons to customers and copies to the team.

**Microsoft Teams**: Receives adaptive cards for subscription events and security alerts in dedicated channels.

**Microsoft-managed AI services**: Speech-to-text, text-to-speech, and generative models used for orchestration and answers.

## Scenario details

### Business challenge

Routine account requests take a large share of contact center time. Automating them is valuable only if the agent can prove who is calling, change data without errors, and leave a complete record. Voice cloning and recorded voices make caller verification harder, and representatives need context when the agent hands over a call.

### Solution

The agent combines a natural conversation with strict process steps:

- Verification by voice biometrics with a PIN fallback, and an explicit result message in every path.
- A server-side verification check in every flow that changes data, so the orchestration can't skip verification.
- Deterministic agent flows for every account change, each followed by a timeline note, a case, and a customer email with Confirm and Undo.
- Handoff with a summary to a representative in the same contact center.
- Real-time visibility for internal teams in Microsoft Teams, including a separate channel for security alerts.

The agent runs today in Dynamics 365 Contact Center: customers reach it through the Contact Center phone number, Teams Phone, and web chat. Contact Center Intelligence also connects to other contact center platforms, so the same agent design can be used with an existing contact center where routing and telephony stay in place.

### Potential use cases

- Subscription and membership management.
- Utilities or telecommunications account changes, such as tariff changes or service suspension.
- Insurance policy information and simple policy changes.
- Any scenario that requires strong caller verification before account changes.

## Considerations

These considerations implement the pillars of Power Platform Well-Architected, a set of guiding tenets that improve the quality of a workload. Learn more in [Microsoft Power Platform Well-Architected](/power-platform/well-architected/).

### Reliability

**Make data changes idempotent**: Design each flow so that a repeated call doesn't change the record twice. For example, the cancel flow returns *AlreadyCancelled* when the subscription is already cancelled.

**Handle failures in one place**: Use a Try scope and a Catch scope in each flow, and return a single result value to the agent (for example *Cancelled*, *NotFound*, *NotVerified*, or *Error*). Keep the main change when only a follow-up step, such as the note or the email, fails.

**Prevent trigger loops and duplicate notifications**: The agent flows and representatives in the app change the same column. Record who made each change in the same update as the change itself: agent flows write a change stamp (the date and time of the agent change), and a form script clears the stamp when a representative changes the status in the app, so an app change never inherits an old agent value. The trigger condition of the Dataverse-triggered flow runs only for app changes (empty stamp). As a safety net for app edits that don't run the form script, such as editable grids, the condition also treats a stamp older than 60 seconds as an app change. A dedicated *change source* column (*Agent* or *App*) set by every writer works the same way. The triggered flow doesn't update the subscription itself, so it can't trigger itself again.

Don't rely on a time window alone: a representative change made shortly after an agent change would be skipped.

**Don't make the caller wait for notifications**: The security alert flow responds to the agent first and then posts to Teams, so a slow external service never delays the conversation.

### Security

**Verify on the server side**: Every flow that reads or changes customer data checks that the contact was verified in the current conversation ID and that the verification hasn't expired. A prompt or a wrong orchestration decision can't bypass this check.

**Limit attempts**: Lock PIN verification for 24 hours after three failed attempts, and alert the security team.

**Protect sensitive input**: Mark the PIN question as sensitive, clear the PIN variable after use, and encourage keypad input for the PIN.

**Treat fraud signals as a hard stop**: When voice biometrics returns *FraudDetected*, make no changes, hand off to a representative with a warning, and alert the security team without notifying the customer.

**Protect action links**: The signature in an HTTP trigger URL only authorizes calling the flow. It doesn't authorize a specific customer, record, or operation, and email security scanners and link previews can open links automatically. Protect Confirm and Undo links in three ways:

- **Separate the link from the action**: The link in the email opens a confirmation page that changes nothing. Only an explicit selection of the button on the page runs the change. For stricter control, serve the page from Power Pages and send the change as a POST request.
- **Use a single-use, expiring token**: When a flow sends the email, it creates a token row in Dataverse that is bound to the record, the operation, and the customer, with an expiry time (for example 72 hours). The *Email response* flow accepts the request only when the token exists, matches the record and operation, hasn't expired, and hasn't been used. It marks the token as used in the same transaction as the change.
- **Validate the transition**: Before any change, check that the requested operation is valid for the current record state, for example Undo cancellation only when the subscription is cancelled.

Never publish the trigger URL outside these emails, and rotate it if it leaks.

**Add layers when the risk requires it**: Contact Center supports an SMS one-time code during the call in addition to voice biometrics. For higher assurance, you can integrate an authenticator app code that the customer types on the keypad.

### Operational Excellence

**Use solutions and connection references**: Keep the agent, flows, tables, and connection references in one solution so you can move them between environments.

**Evaluate the agent continuously**: Create test sets and use [agent evaluation](/microsoft-copilot-studio/analytics-agent-evaluation-intro) in Copilot Studio after each change. Use the Copilot Studio Kit for repeatable regression tests of verification and cancellation paths.

**Give the team visibility**: Post subscription events and security alerts to Microsoft Teams channels so the right team sees them without opening the contact center application.

### Performance Efficiency

**Split responsibilities between agents**: Keep verification and wrap-up in the primary agent and move each business domain to its own sub-agent. Smaller instructions make the agent more precise.

**Use agent flows for deterministic work**: Use flows for anything that must happen the same way every time, such as price lookup from the catalog, ID generation, and duplicate checks. The agent never sets prices or IDs itself.

### Experience Optimization

**Say the result out loud**: Tell the customer whether verification succeeded and why the next step happens, in both voice and chat.

**Support speech and keypad**: Let customers say or type numbers, and finish keypad input with the pound key.

**Let customers correct mistakes**: Every change email has Confirm and Undo buttons.

**Hand off with context**: Pass a summary to the representative, so the customer doesn't repeat information.

## Responsible AI

**Transparency**: Tell customers that they're talking to an AI agent and when the conversation moves to a person.

**Consent for voiceprints**: Enroll a voiceprint only after successful verification and with the customer's consent, and provide a way to remove it.

**Human in the loop**: Every change creates a case that a representative reviews. Suspected fraud always goes to a person.

**Data minimization**: Store only the verification fields the flows need, such as the verified conversation ID and expiry time.

## Contributors

*Microsoft maintains this article. The following contributors wrote this article.*

Principal author:

[**Magdalena Kaczkowska**](https://www.linkedin.com/in/magdalena-kaczkowska-powergirl/), Power Platform Solution Architect & Agentic AI Expert in Dynamics 365

## Related resources

- [Microsoft Copilot Studio documentation](/microsoft-copilot-studio/)
- [Voice-enabled agents in Copilot Studio](/microsoft-copilot-studio/voice-overview)
- [Hand off to a live agent](/microsoft-copilot-studio/advanced-hand-off)
- [Establish an application lifecycle management strategy for agents](/microsoft-copilot-studio/guidance/alm)
- [Dynamics 365 Contact Center documentation](/dynamics365/contact-center/)
- [Power Platform Well-Architected](/power-platform/well-architected/)
