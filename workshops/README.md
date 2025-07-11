

# Workshops templates
The business process catalog includes comprehensive set of workshop templates designed to streamline collaboration and decision-making across key business areas. These templates are structured to enhance engagement and ensure precise alignment with business goals. Below, you’ll find the core structure of the workshops, a detailed list of processes that include workshops in this release, and an overview of the three distinct workshop types: Storyboard, Storyline Design Review, and Deep-Dive Design.

## Workshop template structure
Each workshop template includes:
-	A clear agenda to guide participants through the session’s objectives.
-	Pre-defined tools and resources tailored to facilitate effective collaboration.
-	Comprehensive instructions to ensure consistency and alignment with best practices.

The templates are designed to be flexible and scalable, accommodating the unique needs of sellers, technical sellers, solution architects, and business analysts or functional consultants.

## Processes featuring workshops 
The following end-to-end processes include Word document templates for the business process catalog
- Acquire to dispose
-	Design to retire
-	Forecast to plan
-	Inventory to deliver
-	Hire to retire
- Order to cash
- Prospect to quote (Public Preview)
- Source to pay

## Workshop types
Three workshop types are included for each end-to-end process. Each workshop template is tailored to specific stages of the business process design and refinement.
-	Storyboard design workshops

These workshops are highly visual and focus on mapping out the entire business process. Participants collaborate to create a high-level overview of the business processes, scenarios, and objectives, identifying key milestones and potential bottlenecks. The objective is to establish a shared vision and roadmap. These workshops are recommended to be run early in the pre-sales stage of an engagement to help the team get a better understanding of the customers business needs and create a demo plan. 

Each storyboard design workshop includes the following components:
  -	A storyboard graphic in the Visio file that is available for the end-to-end business process in the GitHub repository. The Visio files can be downloaded at https://aka.ms/businessprocessflow.  
  -	A Word document template for the workshop. The Word document template files can be downloaded at https://aka.ms/businessprocessworkshops. 
  -	Work items in the Azure DevOps template. This includes one Workshop type work item for the overall workshop including the details of the workshop from the template, and Tasks that are children work items under the parent Workshop work item. 

-	Storyline design review workshops

In these sessions, the primary scenario is demonstrated to the customer in Dynamics 365. Teams delve into the specifics of the business process in Dynamics 365. The goal is to review and refine the storyline behind the process and conduct a fit-to-standard analysis, ensuring all steps are aligned with strategic objectives. Feedback loops are built into the session to address gaps or inconsistencies. 

Each Storyline design review workshop includes the following components:
  -	A Word document template for the workshop. The Word document template files can be downloaded at https://aka.ms/businessprocessworkshops. 
  -	Work items in the Azure DevOps template. This includes one Workshop type work item for the overall workshop including the details of the workshop from the template, and Tasks that are children work items under the parent Workshop work item. 

-	Deep-dive design workshops

These workshops are designed for thorough exploration of intricate process details. The focus is on addressing complex challenges, testing assumptions, and finalizing designs. They are particularly useful for processes requiring cross-functional alignment and technical input. These workshops are intended to be run by the implementation team in the Implement phase of a project. Each level two business process area in the catalog includes at least one Deep-dive design workshop. However, some business process areas may include multiple workshops. 

  -	A Word document template for the workshop. The Word document template files can be downloaded at https://aka.ms/businessprocessworkshops.
  -	Work items in the Azure DevOps template. This includes one Workshop type work item for the overall workshop including the details of the workshop from the template. These workshops do not include detailed tasks. However, the catalog includes Configuration deliverables which make up much of the work functional consultants would need to do in order for the process to work according to the customers business requirements. 

## Using the workshop templates in Azure DevOps

While there is not one specific way to use the templates and work items provided in the business process catalog, the following list of tips and tricks can be used to help ensure good management and governance of the process:
-	Document each business requirement using Requirement type work items. 
- Document Risks, Issues, Actions, and Decisions (RAID) log items using the related work item types. 
- Create Task type work items to track specific tasks that need to be completed or followed up on by the project team. 
- Work items should be linked to the lowest possible level of the business process catalog, typically level four scenarios. However, if a business requirement is more general, it may be appropriate to link it to a higher-level business process or area.

