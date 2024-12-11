---
title: Power Pages with Finance and Operations Apps
description: Learn about building Power Pages on data places in Finance and Operations database
author: Ted Ohlsson
ms.author: 
ms.topic: article
ms.date: 
---

# Power Pages with Finance and Operations Apps

***Applies to: Dynamics 365 Supply Chain Management, Dynamics 365 Finance, Dynamics 365 Project Operations, Dynamics 365 Human Resources, Power Pages, Dual-write, Virtual entities for finance and operations apps, Dataverse, XDS***

This article describes the different functionalities that can be leveraged to interact with data from the Dynamics 365 Finance and Operations database in Power Pages.


## Introduction

The core use case where you would use this functionality is when you are running or implementing a Finance and Operations Apps-based solution, like Dynamics 365 Supply Chain Management or Dynamics 365 Finance, and need external users to interact with some of that data. Examples of data you want to interact with could be purchase orders, sales orders, workers, etc.
There are two main ways of doing it: 
1. Integrating the data between Dataverse and Finance and Operations database via [Dual-write] (https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/data-entities/dual-write/dual-write-overview) or other integration engines
2. Running it directly on the Finance and Operations database via [Virtual entities for finance and operations apps] (https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/power-platform/virtual-entities-overview)


## Power Pages

[Power Pages] (https://learn.microsoft.com/en-us/power-pages/introduction) is [hardly coupled to Dataverse] (https://learn.microsoft.com/en-us/power-pages/admin/architecture) and can't be run without a Dataverse. When having the data within Dataverse security roles called [web roles](https://learn.microsoft.com/en-us/power-pages/security/power-pages-security) can be created and assigned to a specific external user, giving them access to, in the web role, a predefined subset of data through a Power Pages portal.

## Dual-write and Integration engines

In these scenarios, the data that the external users are to communicate with are stored in both Dataverse and the Finance and Operations database. When changes are made in Finance and Operations, they are then integrated into Dataverse. Once updated in Dataverse, they can be read from Power Pages. Changes made from Power Pages are stored in Dataverse and then integrated into Finance and Operations.

These integrations can be trigger-based synchronous, trigger-based asynchronous or bach-based. Dual-write can be leveraged in trigger-based synchronous and trigger-based [asynchronous scenarios](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/data-entities/dual-write/dual-write-async).

All communication, regardless of the integration platform, needs to be run through the [Finance and Operations Data Entities] (https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/data-entities/data-entities), and there needs to be applicable Data Entities in place containing the data that you want the external users to interact with.

In these scenarios, the integration between Dataverse and the Finance and Operations database is done with admin accounts, and the security handling for the external users can be handled with [web roles] (https://learn.microsoft.com/en-us/power-pages/security/power-pages-security) just as in a stand-alone Dataverse Power Pages solution.

:::image type="content" source="../media/dual-write-power-pages.svg" alt-text="Diagram showing data flowing in between Dynamics F&O and Power Pages via Dual-Writes" lightbox="../media/dual-write-power-pages.svg ":::


## Virtual entities for finance and operations apps

In the Virtual entities for finance and operations apps (VE) scenarios, the Power Page reads directly from the Finance and Operations database, and the data is only stored within the Finance and Operations.

When running data through VE to Power Pages, this can be done both as [authenticated access and anonymous access] (https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/power-platform/power-portal-reference). In both the VE authenticated and the VE anonymous scenarios you give the external user access to one or several Finance and Operations data entities an add a web role on them. 

There is a security aspect that's important to keep in mind in these scenarios. By default, you cannot restrict a Finance and Operations user in a specific table or a data entity (within the same legal entity) from only seeing siren parts of the data.

Even though you restrict external users' access to the web role, the external user can still use the credentials to directly target the data entity in finance and operations and read all the data that the user is allowed to read from the data entity.

Example:
You have created a Power Page portal where vendors can log in and see all their purchase orders and purchase order lines. A vendor should only be able to see its own purchase orders and purchase order lines and not its competitors. The restriction of only seeing your own purchase orders and purchase order lines can be set up in the web role. Still, the possibility of targeting the data entities directly and seeing all your competitor's purchase orders and purchase order lines is there.

In these scenarios, you need to use authenticated access and set up a table to connect the umbrella table (the one defining what the users are allowed to see, vendor in the above example) and the user. Connected to that table, you then build [Extensible data security policies (XDS)] (https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/sysadmin/extensible-data-security-policies) that only allow a user to read data linked to the umbrella table. In the above example, that would restrict a vendor from seeing only its own purchase orders and purchase order lines.

:::image type="content" source="../media/ve-power-pages.svg" alt-text="Diagram showing data flowing in between Dynamics F&O and Power Pages via Virtual entities for finance and operations apps " lightbox="../media/ve-power-pages.svg":::

## Related information
- [Dual-write] (https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/data-entities/dual-write/dual-write-overview) or other integration engines
- [Dual-write Asynchronous Scenarios](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/data-entities/dual-write/dual-write-async)
- [Virtual entities for finance and operations apps] (https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/power-platform/virtual-entities-overview)
- [Finance and Operations Data Entities] (https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/data-entities/data-entities)
- [Power Pages] (https://learn.microsoft.com/en-us/power-pages/introduction)
- [Power Pages Aritecture] (https://learn.microsoft.com/en-us/power-pages/admin/architecture)
- [Web roles](https://learn.microsoft.com/en-us/power-pages/security/power-pages-security)
- [Authenticated access and Anonymous access Portal Access] (https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/power-platform/power-portal-reference)
- [Extensible data security policies (XDS)] (https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/sysadmin/extensible-data-security-policies)

## Contributors

*This article is maintained by Microsoft. It was originally written by the following contributors.*

Principal author:

- [Ted Ohlsson]( https://www.linkedin.com/in/tedohlsson/)\| Dynamics 365 Architect

