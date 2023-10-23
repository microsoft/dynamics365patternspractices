---
title: 
description: 
ms.date: 10/23/2023
ms.topic: article
ms.service: 
author: rachel-profitt
ms.author: raprofit
manager: 
---

# Importing the business process catalog into Azure DevOps

This articles describes how you can use the business process catalog as a template to import into an Azure DevOps project for managing your Dynamics 365 implementation project.

## Why should you import the business process catalog into Azure DevOps?

There are many reasons why using a tool like Azure DevOps is critical to the overall success of a Dynamics 365 implementation. When you use a tool such as Azure DevOps together with the business process catalog you can accelerate your deployment and follow the recommendations made in the Dynamics 365 Implementation Guide Process-focused solutions guidance. The following are just some of the benefits of using the catalog to import into Azure DevOps to manage your Dynamics 365 implementation.

- **Efficiency and time savings**: The Microsoft Business Process Catalog provides a standardized and comprehensive list of business processes. This catalog can save customers and partners a significant amount of time that would otherwise be spent on researching, defining, and documenting business processes from scratch.

- **Recommended practices and industry standards**: The documentation that accompanies the catalog which can be found in the Dynamics 365 guidance hub often includes recommended practices and industry-standard business processes. Leveraging these pre-defined processes can help ensure that technology solutions align with recognized industry standards and compliance requirements.

- **Reduced risk**: Using established and standardized processes reduces the risk of errors and oversights in the implementation of technology solutions. These processes have often been tried and tested, reducing the chances of costly mistakes.

- **Alignment with Microsoft technologies**: The catalog is designed to work seamlessly with Microsoft technologies, including Dynamics 365, Power Platform, and Azure. This alignment can simplify integration and interoperability, making it easier to build and deploy technology solutions.

- **Scalability**: As businesses grow, their processes may need to evolve. The Business Process Catalog provides a foundation that can be scaled and customized as needed, ensuring flexibility for future changes.

- **Community and collaboration**: Utilizing a standardized catalog fosters collaboration and knowledge sharing within the Microsoft community. Customers and partners can benefit from the experiences and insights of others who have used similar processes.

- **Training and onboarding**: When new employees or team members join an organization, having standardized processes in place can streamline their onboarding and training. It provides a clear reference point for understanding how the organization operates.

In conclusion, the Microsoft Business Process Catalog offers customers and partners a valuable resource for implementing technology solutions efficiently, effectively, and in alignment with industry standards. It simplifies the process of designing, customizing, and deploying solutions, ultimately leading to improved productivity, reduced risk, and better business outcomes.

## Before you import

Before you can import the project into Azure DevOps, there are a few things that you will need to do and consider. Use the following information as a guide and checklist to ensure that you are ready to import the catalog into Azure DevOps.

1.  Define your project scope. We suggest that you use the spreadsheet as a starting point to define the scope. At the most fundamental level this is done by deleting any rows that are not applicable to your project. For more information and guidance about defining your project scope, refer to [Process-focused solution.](https://learn.microsoft.com/en-us/dynamics365/guidance/implementation-guide/process-focused-solution)

2.  [Create an Azure DevOps project](https://learn.microsoft.com/en-us/azure/devops/organizations/projects/create-project?view=azure-devops&tabs=browser) in the customer tenant. The template we have provided is designed to work with the Agile **Work item process type**.

3.  Define area paths in the Azure DevOps project settings. For each end-to-end process that is in scope, create one area path. For more information, refer to [Define area paths and assign to a team.](https://learn.microsoft.com/en-us/azure/devops/organizations/settings/set-area-paths?view=azure-devops&tabs=browser)

4.  Insert any additional rows required for your project. This can include additional Epics, Features, or User stories. Epics use the first Title column, Features use the second Title column, and User stories use the third Title column. To ensure a relationship is established between the rows, the Next Epic or Feature row should not be inserted until all rows that required a relationship to the last Epic or Feature are inserted into the spreadsheet. You may want to consider adding additional work items types too such as Configuration or Workshops for example, but the template provided does not include other work item types.

5.  Complete the additional columns in the spreadsheet as required. Use the following recommendations to guide you.

    1. **Description** – in future releases we plan to pre-populate this column for you. You can optionally add a detailed description for your business processes prior to importing or work on this gradually throughout the project.

    2. **Assigned to** – this is typically the consultant or person who is responsible for configuring the process from the Partner organization. Make sure the person is already added as a user to your project.

    3. **Business owner** – this is typically the stakeholder from the customer organization that is responsible for the business process. Make sure the person is already added as a user to your project.

    4. **Business process lead** – this is typically the subject matter expert from the customer organization that is responsible for the business process. Make sure the person is already added as a user to your project.

    5. **Tags** – You can optionally create tags for sorting, filtering, and organizing your work items. The default template does not include any tags. We recommend you consider using this column for separating departments, phases, geographic regions, or product families such as customer engagement versus finance and operations apps, for example.

    6. **Priority** – All rows in the spreadsheet are defaulted to a Priority of "1". We recommend that you review the priorities using "1" for all "must have" features and "3" for all "nice to have features". You can define your own definitions too, we recommend that you document the definitions for your project team.

    7. **Risk** – optionally, you can add a rating for the risk. For example, you may give processes a high risk score if there is a lot of complexity or modification required to the process.

    8. **Effort** – optionally, you can add a rating for the effort. For example, you may give processes a high effort score that are going to require integration or modification.

6.  Update the **Area path** in the file. You will need to replace the value in the Area path with the exact name of your project and area paths. If you create the areas paths to match the end to end process names, you only need to replace the following text "DevOps Product Catalog Working Instance" with the name of your project in your Area path.

7.  You can optionally add more columns to the file or remove columns that will not be used prior to importing. If you add custom fields to your Azure DevOps project that are mandatory, be sure to include them in the file or the file may fail to import.

8.  Split large files for import. You will need to determine if you need to split your file into multiple files for uploading. Azure DevOps has a limit of 1000 rows that can be uploaded in one import. If your final file has more than 1000 rows you will need to split the file. It is critical that when you split the file, all Epics, Features, and User stories that are related to the same end-to-end process need to be combined into the same file. For example, if row 1000 is in the middle of the Order to Cash process after deleting and inserting any required rows, you will want to split the file at the first row for Order to Cash to ensure that all Order to cash processes are included and the relationships can be established during import. If you are attempting to import the entire catalog, you will need to split the file into four parts for importing.

9.  The file must be saved as a CSV file to be imported into Azure DevOps. If you have added extra columns and features into the spreadsheet that you do not want to loose such as formatting or formulas, consider saving a version of the file as an XLSX file in order to not loose those features, but the version you import must be CSV.

## Importing the file

Once you have prepared your file for import and configured the basic setup in the Azure DevOps project with area paths, security, teams, and users, you can import your work items following the steps provided here: [Import update bulk work items with CSV files](https://learn.microsoft.com/en-us/azure/devops/boards/queries/import-work-items-from-csv?view=azure-devops).

## After you import

After you import the file, you will want to validate the import was successful. If the file import fails, use the messages provided to help guide you to correct the issue and then try again. Once the file is imported successfully you can begin managing your project using the features of Azure DevOps. The following are a few tasks and tips to consider.

-   Create a backlog. [Use backlogs to manage projects - Azure Boards \| Microsoft Learn](https://learn.microsoft.com/en-us/azure/devops/boards/backlogs/backlogs-overview?view=azure-devops)

-   [Implement Scrum work practices in Azure Boards - Azure Boards \| Microsoft Learn](https://learn.microsoft.com/en-us/azure/devops/boards/sprints/scrum-overview?view=azure-devops)

-   Create queries to manage the work. [Use managed queries to list work items - Azure Boards \| Microsoft Learn](https://learn.microsoft.com/en-us/azure/devops/boards/queries/about-managed-queries?view=azure-devops)

-   Analyze your projects progress. [Analytics & Reporting - Azure DevOps \| Microsoft Learn](https://learn.microsoft.com/en-us/azure/devops/report/?view=azure-devops)

