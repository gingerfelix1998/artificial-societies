# artificial-societies
LLM orchestration for artificial societies task. The task is specified below:

We’d love for you to build 100 LLM personas modelling one group of humans, and use this group to inform a consequential decision. Your goal is to come up with different methods of creating / modelling personas using LLMs, so that they produce results that capture the human group’s opinions and inform the decision as much as possible. You may be asked present your conclusions and defend your methods to senior decision-makers.

Our approach will use a small society of individuals to simulate nuclear escalation dynamics for a given situation.


## Chosen Domain:
In this particular example, I want to capture the nuclear strategists responsible for the literature that defines current norms in International Relations covering the nuclear security domain. I then want to simulate the response to a certain situation.

**President:**
These are representing the key decision maker for a given nuclear-armed nation. They are briefed on a situation by an 'Intelligence Officer', they then speak to their 'Advisor' to understand the context, before making a decision. They will have their own belief system and biases for responding to a situation, but they will take the advice of their advisors into account.

**Advisor:**
I then want to create the 'advisor', who is an knowledgeable professional across all of the different theorists' work. The advisor is asked a question by the 'President' and then engages with the different 'Theorists' to create a sumarised brief to provide to the 'President'.

**Theorist:**
These are the individual academic theorists who are experts in their given domains. They have their own literature as reference material to answer questions asked of them by 'Advisor' agents.

**Intelligence Officer**
The intelligence Laiason Officer who will provide a series of updates to the 'President' as new events happen in the simulation.

### Society
'Intelligence Officers' have read access to real-world events, that will be provided by the simulation host at given times. These are the events they feed to the 'President' as updates.

The 'President' is the only individual with write access to the real-world, for other nations' 'Intelligence Officer' agents to read and process.


### Scope:
Initially, start with a single simulation. This would be a one-time response of the community to an event, added to the simulation as a message that propogates. The 'Intelligence Officer' reads the event and briefs the 'President'. The internal loop occurs for that nation state, and ends with the 'President' providing a response into the real-world. This is a one-event, closed feedback loop for a single nation.

Second, we will have multiple nations involved and the Presidents will be signalling to each other throughout the scenario. This gives us the opportunity to observe escalation dynamics.

Then, we will expand to a comparative analysis of two time periods. Potentially, observe escalation dynamics for the same situation across two distinct time periods. Alternatively, re-create historical situations with different context or theoretical literature.