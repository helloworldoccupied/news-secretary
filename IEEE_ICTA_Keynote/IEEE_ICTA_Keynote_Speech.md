# Keynote Speech Script
## From Cloud to Edge: Building AI Computing Infrastructure for the Age of Embodied Intelligence
### Chao Chen | IEEE ICTA 2026 | Singapore
---

## PART 1: OPENING — Three Waves of Compute (4 min)

**[SLIDE 1: Title slide]**

Good morning, everyone. Thank you to the IEEE ICTA organizing committee for the invitation. It's a privilege to be here at a conference dedicated to advancing integrated circuits with AI.

My name is Chao Chen. I'm going to talk about AI computing infrastructure — but not from the chip designer's perspective. I'm going to talk about it from the other side: the perspective of someone who deploys chips at scale, who operates the data centers they go into, and who invests in the robots that will need them next.

**[SLIDE 2: Three Waves]**

Let me start with a personal observation. In my career, I've lived through what I call three waves of compute demand.

The first wave was quantitative trading. I started my career in quantitative finance, building systems where microseconds mattered and computational throughput directly translated to profit. In that world, I learned a fundamental lesson: computing power is not an IT cost — it's the core production asset. Every cycle of latency, every watt of power, every minute of downtime has a price tag.

The second wave is AI training. Over the past several years, I've been building and operating intelligent computing centers in China — large-scale GPU clusters for training foundation models. This is where I learned that a single chip's performance is just the beginning of the story. The real challenges are thermal management, power delivery, network interconnection, and utilization — all system-level problems that no chip design alone can solve.

The third wave is just beginning: embodied intelligence. I'm an investor in two humanoid robotics companies — LingShen Technology and TIEN Kung, the Beijing Humanoid Robot Innovation Center. Through these investments, I've seen an entirely new set of computing demands that are fundamentally different from anything in the data center.

**[SLIDE 3: Compute demand curve]**

Here's the big picture. According to Deloitte, inference workloads will account for roughly two-thirds of all AI compute in 2026 — up from one-third in 2023. The market for inference-optimized chips alone will exceed 50 billion US dollars this year. And the embodied AI market is projected to grow from 4 billion to over 60 billion in the next decade, at a 31% compound annual growth rate.

The demand for compute is not just growing — it's diversifying. And each new form of compute creates new demands on IC design.

So today I want to take you on a journey from the cloud to the edge to the robot's body — and at each stop, I'll share what I've learned about what chip designers need to know.

---

## PART 2: Cloud Scale — Lessons from Operating Intelligent Computing Centers (8 min)

**[SLIDE 4: Section title — "The Cloud: Operating AI at Scale"]**

Let me start with the data center.

**[SLIDE 5: Scale of the challenge]**

China has built over 200 intelligent computing centers in the past three years. I've been directly involved in several of these. And I can tell you that the most important lessons I've learned have nothing to do with chip specifications.

When you operate thousands of GPU accelerators in a single facility, the system-level challenges dominate everything. Let me walk you through the top three.

**[SLIDE 6: Challenge 1 — Thermal]**

Challenge number one: thermal management.

A single high-end AI accelerator now consumes 700 watts or more. A fully loaded rack can draw 40 to 80 kilowatts. At this power density, traditional air cooling simply cannot keep up.

In our facilities, we've transitioned from air cooling to liquid cooling, bringing our PUE — Power Usage Effectiveness — from approximately 1.4 down to 1.15. That 0.25 reduction translates directly to millions of dollars in annual energy savings and, more importantly, to stable chip operating temperatures that extend hardware lifetime.

The takeaway for IC designers: your chip's thermal design power is not just a spec on a datasheet. It directly determines what kind of cooling infrastructure is required, which in turn determines the total cost of ownership for your customers. Reducing TDP by even 50 watts can change the economics of an entire data center deployment.

**[SLIDE 7: Challenge 2 — Power]**

Challenge number two: power supply.

One thousand GPU accelerators consume approximately one megawatt of power. A large intelligent computing center may have ten to fifty thousand cards. That's 10 to 50 megawatts — the electrical load of a small town.

In China, this has led to a geographic redistribution of AI infrastructure. Computing centers are increasingly built in western provinces — Guizhou, Inner Mongolia, Gansu — where electricity costs one-third of what it costs in Beijing or Shanghai. Power is the new oil of the AI era.

For chip designers, this means performance per watt is arguably more important than absolute performance. A chip that delivers 90% of the FLOPS at 70% of the power will win in large-scale deployment every time.

**[SLIDE 8: Challenge 3 — Utilization]**

Challenge number three: utilization.

This one surprised me. The average GPU utilization rate across China's intelligent computing centers is estimated at less than 30 percent. We buy enormous amounts of compute capacity, and most of it sits idle.

Why? Multi-tenant scheduling is hard. Job preemption and migration are complex. Memory fragmentation between models of different sizes is a real problem. And when a card fails — which happens daily at scale — the recovery and redistribution process can waste hours of cluster time.

We've invested heavily in scheduling software, automated fault detection, and predictive maintenance. But the fundamental problem remains: hardware that is not designed for multi-tenant, fault-tolerant operation at scale creates utilization problems that no software layer can fully solve.

**[SLIDE 9: Summary — Cloud lessons for IC]**

So here are the cloud-scale lessons for IC designers:

First, design for system deployability, not just benchmark performance. A chip that runs hot, draws excessive power, or lacks diagnostic capabilities creates downstream costs that dwarf the chip's purchase price.

Second, power efficiency is king. In large-scale deployment, performance per watt matters more than peak performance.

Third, build observability into the silicon. Remote monitoring, temperature reporting, error logging — these features are not nice-to-haves. At scale, they are operational necessities.

And fourth, reliability over years, not hours. We need chips that run stable at 85% load for 365 days, not chips that hit a record benchmark for 60 seconds.

---

## PART 3: Embodied Intelligence — Computing's Next Frontier (12 min)

**[SLIDE 10: Section title — "The Edge and Beyond: When Compute Leaves the Data Center"]**

Now I want to shift gears dramatically.

Everything I just described — liquid cooling, megawatt power supplies, high-speed interconnects — assumes the chip lives in a data center. But what happens when compute needs to leave the data center and walk around on two legs?

**[SLIDE 11: Why I invest in robots]**

A few years ago, I started asking: what comes after the data center? Where does AI compute go next? The answer, I believe, is into the physical world — into robots, vehicles, and industrial equipment.

This is why I invested in two companies that I think represent the future of embodied intelligence.

**[SLIDE 12: LingShen Technology]**

The first is LingShen Technology, a company founded by a Tsinghua University team in 2023. LingShen is building what they call a "universal brain platform" for humanoid robots. They've developed their own real-world data collection platform — called LDP — and an embodied world model called LWM. These systems enable robots to perceive, reason, and act in unstructured environments.

LingShen has already deployed in smart manufacturing, unmanned retail, and healthcare settings, and recently completed over 100 million RMB in Pre-A financing.

**[SLIDE 13: TIEN Kung]**

The second is TIEN Kung, developed by the Beijing Innovation Center of Humanoid Robotics — a national-level platform supported by the Ministry of Industry and Information Technology.

TIEN Kung was the world's first purely electric-driven full-size humanoid robot capable of human-like running at 6 kilometers per hour. Just this February, they released version 3.0 — the first full-size humanoid with touch-interactive, high-dynamic whole-body motion control. And critically, they've chosen an open-source path, making their platform available to the broader ecosystem.

**[SLIDE 14: The investor's question]**

When I talk to the engineering teams at both companies, I always ask the same question: what is your biggest bottleneck?

The answer is never funding. It's never algorithms — those are advancing rapidly. The answer is consistently the same: on-body compute. The available edge and embedded processors simply cannot deliver what we need within our power and size constraints.

And that brings us directly to the IC design challenge.

**[SLIDE 15: Cloud vs. On-body comparison table]**

Let me show you why this is so hard.

Here is a comparison between what cloud AI chips deliver today and what embodied AI needs.

In the cloud, compute is measured in petaFLOPS — the more the better. On a robot body, you need teraOPS — adequate, not maximum — because every excess transistor costs power.

In the cloud, a chip can consume 700 watts because it sits in a liquid-cooled rack. On a robot running on batteries, your total compute power budget is 30 to 50 watts. That's a 15x reduction.

In the cloud, inference latency of one second is often acceptable. For a robot walking among people, you need sensor-to-actuator response in under 10 milliseconds. If the robot hesitates for one second before catching its balance, it falls over.

In the cloud, when a chip fails, you swap it out and restart the job. On a robot working alongside humans, there is no redundancy. The chip cannot fail.

And perhaps most importantly: in the cloud, chips typically run a single model type — one training job at a time. A robot must simultaneously run computer vision, language understanding, tactile processing, and motor control — all on the same silicon.

**[SLIDE 16: The core challenge in one sentence]**

Let me put it simply:

Cloud computing's challenge is fitting chips into racks. Embodied computing's challenge is fitting racks into bodies. These require fundamentally different IC design philosophies.

**[SLIDE 17: Cloud-Edge-Body architecture]**

Now, the good news is that robots don't have to do everything locally. The architecture that's emerging is a three-tier system.

At the top: the cloud — our intelligent computing centers. This is where models are trained and world models are updated. It runs on the timescale of hours and days.

In the middle: edge servers, located at the factory floor or warehouse. These run scene-specific inference models and coordinate multi-robot operations. Response time is in the hundreds of milliseconds.

At the bottom: on-body compute — the SoC or NPU inside the robot itself. This handles real-time perception, safety-critical control, and autonomous decision-making. Response time must be under 10 milliseconds.

**[SLIDE 18: IC implications of three-tier]**

Each tier creates different IC demands.

The cloud tier — we know this well. It's today's GPU and AI accelerator market. The challenges are scale, power, and interconnect, as I described.

The edge tier is where the inference chip market is exploding. We need high-throughput inference at moderate power — think 100 to 300 watts — with support for multiple model types and real-time scheduling.

The on-body tier — this is the wide-open frontier. We need SoCs that integrate heterogeneous compute — CNN accelerators for vision, transformer engines for language, dedicated control processors for motion planning — all in a package that fits in a robot's torso and runs on less than 50 watts.

This third tier is, in my view, the single largest greenfield opportunity for IC designers in the next decade.

---

## PART 4: Recommendations for IC Designers (5 min)

**[SLIDE 19: Section title — "What IC Designers Can Do"]**

So let me synthesize what I've learned from operating at cloud scale and investing at the robot edge into specific recommendations for this community.

**[SLIDE 20: For cloud/data center chips]**

For cloud and data center chip designers:

One — prioritize performance per watt over absolute performance. Your customers' biggest cost is electricity, not your chip.

Two — standardize chip-to-chip interconnect interfaces. Proprietary interconnects create vendor lock-in that slows industry adoption and increases integration costs.

Three — build diagnostics and monitoring into the silicon. Remote health reporting, error counters, thermal sensors — these are not optional features. They are what makes large-scale operation viable.

Four — design for multi-tenant workloads. Hardware-level memory isolation, secure context switching, quality-of-service guarantees — these features directly improve utilization rates.

**[SLIDE 21: For edge/embodied chips]**

For edge and embodied computing chip designers:

One — heterogeneous compute is not a nice-to-have, it is a requirement. A humanoid robot needs CNN, transformer, and real-time control processing on a single die. Dedicated accelerators for each modality, sharing a unified memory system.

Two — power is the hard constraint, not performance. Design to a 30-to-50-watt envelope first, then maximize compute within that budget. If you have to sacrifice TOPS to meet the power budget, do it.

Three — latency matters more than throughput. A robot needs one inference result in 5 milliseconds, not a thousand results per second. Optimize for single-sample latency.

Four — safety and reliability are non-negotiable. These chips will operate inside machines that work alongside humans. Functional safety certification, error detection and correction, graceful degradation under partial failure — these must be designed in from day one.

Five — cost at scale. A 30,000-dollar accelerator card is acceptable for a data center. A humanoid robot that costs 200,000 dollars will never reach mass adoption. The target for on-body compute should be well under 500 dollars.

**[SLIDE 22: The bridging insight]**

The bridging insight — and the thing that connects my experience from quantitative trading through data centers to robotics — is this:

The best chip is never the one with the highest benchmark score. It is the one that runs reliably, efficiently, and affordably in its target deployment environment — whether that's a trading system, a computing center, or a robot's body.

---

## PART 5: Outlook and Closing (3 min)

**[SLIDE 23: Looking ahead]**

Let me close with a look forward.

2026 is being called the year of "inference famine." The demand for inference compute is growing faster than the supply of inference-optimized hardware. This gap will only widen as embodied AI moves from research labs to factory floors.

**[SLIDE 24: Convergence]**

By 2027 and 2028, we expect to see the first wave of mass-produced humanoid robots entering commercial deployment — in logistics, manufacturing, and elder care. Each of these robots will be a mobile computing platform, carrying on its body more processing power than a high-end laptop. The aggregate demand for on-body AI compute will create a market comparable in scale to the smartphone SoC market.

**[SLIDE 25: Call to action]**

For those of you in this room who design integrated circuits — you are designing the nervous system of these future machines. The decisions you make about architecture, power efficiency, and reliability will determine whether embodied AI becomes a reality or remains a laboratory demonstration.

**[SLIDE 26: Closing quote]**

I started my career optimizing compute for financial models, where microseconds meant money. I then built computing centers where power efficiency meant survival. Now I invest in robots where real-time inference means safety.

At every stage, the lesson is the same: great chips don't just compute — they integrate into systems, they operate at scale, and they serve the real world.

The theme of this conference is "Advancing IC with AI." I'd like to add a complement: we also need to advance AI with IC — from the cloud, through the edge, and into the body.

Thank you.

**[SLIDE 27: Thank you + contact]**

---

*[5-minute Q&A follows]*

**Prepared talking points for likely questions:**

Q: How do you see the US chip export restrictions affecting China's AI infrastructure?
A: Focus on the general point that supply chain diversification drives innovation, multiple architecture paths are emerging, and constraint breeds creativity. Avoid geopolitical commentary.

Q: What domestic chips have you deployed, and how do they compare?
A: Speak generally about the maturing domestic ecosystem, improvements in software stack, and the importance of real-world deployment feedback loops between operators and designers.

Q: What's the timeline for mass-produced humanoid robots?
A: Point to the 2025 data — 13,000 units shipped globally. Expect 10x growth by 2028. The bottleneck is not the robot hardware, it's the compute and the training data for embodied models.

Q: Is liquid cooling worth the investment?
A: Yes, unambiguously, for any deployment above 30kW per rack. The ROI is typically 18-24 months from energy savings alone, before counting the reliability improvements.
