---
id: p005_header_enrichment
title: Header enrichment
hide_title: true
---

# Header enrichment

*Status: In review*
*Feature owner: @pbshelar*
*Feedback requested from: @amarpad, @kozat*
*Last Updated: 10/27*

## Summary

This feature would allow operator to enable header enrichment for HTTP traffic.


## Motivation

Example use cases include the following:

**Captive portals**
This is useful for carrier Captive portals to retrieve user context from HTTP headers. AGW can add HTTP header that sets
IMSI and MSISDN of user making the HTTP request.



**Differential service**



## API
Operator can set target URLs in policy rule via orc8r.

## Implementation Phases

The implementation will be done in two phases.

**Phase 1 - MVP**

(October - November 27)

This will add support to append plain text HTTP headers for IMSI and MSISDSN.

**Phase 2 - Advanced Header enrichment**

(December - January)

In the second phase, features will be provided for option to encrypt these headers.
This will also expand header enrichment API via dynamic rule.

## Phase 1

#### User Flow

User needs to set policy rule in orc8r with target URLs and destination IP address.
If destination IP address is not provided all traffic would enter HTTP header enrichment proxy which
would have performance implications.


### Design
#### Proxy choices
There are multiple options for intercepting HTTP traffic from UE and adding headers.

 
#### AGW - API
Various components involved in header enrichment:

![Header enrichment components](assets/he_block_diagram.png)

#### Datapath design

![datapath for pluging in Envoy](assets/envoy-dp-pipeline.png)
