// The company's HSE plan (YI-3/HSE/REV00/JUN-24), said plainly. Section numbers point back to the full plan.

export const HSE_DOC = {
  title: 'Yalavarti Infra HSE Plan',
  number: 'YI-3/HSE/REV00/JUN-24',
  date: '17 June 2024',
  prepared: 'Mr. Sai Kiran Emandi, Safety Manager',
  reviewed: 'Mr. Sriram Bhart Varma, Project Manager',
  approved: 'Mr. Rakesh B, General Manager',
  pdf: 'docs/yalavarti-hse-plan.pdf',
}

export type RuleIcon = 'helmet' | 'height' | 'permit' | 'brief' | 'report' | 'vehicle' | 'clean' | 'stop'
export interface Rule { icon: RuleIcon; title: string; text: string; ref: string }

export const RULES: Rule[] = [
  { icon: 'helmet', title: 'Helmet and safety shoes, always', text: 'A helmet with the chin strap fastened and safety shoes are a must everywhere on site. Only offices and rest rooms are exempt.', ref: '9.1' },
  { icon: 'height', title: 'Harness above 1.8 m', text: 'Above 1.8 metres, wear a full body harness hooked at shoulder height or higher. Never work at height alone.', ref: '9.2' },
  { icon: 'permit', title: 'No permit, no work', text: 'Hot work, work at height, live electrical work and all digging need a permit first. Keep the permit at the work spot.', ref: '5.4' },
  { icon: 'brief', title: 'Briefed before day one', text: 'Nobody starts until the safety team has shown them the site, the exits, and how to report an accident or a fire.', ref: '5.1.1' },
  { icon: 'report', title: 'Report every injury and near miss', text: 'Tell the safety officer at once, however small. A near miss reported today stops tomorrow’s accident.', ref: '8' },
  { icon: 'vehicle', title: '20 km/h on site', text: 'Keep to marked routes, wear seat belts, and never carry people in trucks or trailers.', ref: '5.7' },
  { icon: 'clean', title: 'Clean as you go', text: 'Clear nails, offcuts and rubbish. Never block fire extinguishers, exits or walkways.', ref: '6' },
  { icon: 'stop', title: 'Unsafe? Stop and tell', text: 'If something looks dangerous, stop and tell your supervisor. The safety team stops high-risk work until it is made safe.', ref: '4.1.2' },
]

export const PPE_ALWAYS = 'Helmet with chin strap and safety shoes - for everyone, everywhere on site.'
export const PPE: { work: string; wear: string }[] = [
  { work: 'Excavators, breakers, chippers, drillers', wear: 'Goggles, hand gloves, helmet, safety shoes' },
  { work: 'Mixing cement, concrete, lime mortar, asphalt', wear: 'Safety goggles, gloves, protective footwear' },
  { work: 'Electricians', wear: 'Insulated tools, rubber gloves, electrical-resistant shoes, rubber mat' },
  { work: 'Grinders', wear: 'Goggles, leather hand gloves' },
  { work: 'Gas cutters and welders’ helpers', wear: 'Coloured goggles, leather hand gloves' },
  { work: 'Welders', wear: 'Welding screen, rubber-soled safety shoes, leather hand gloves' },
  { work: 'Insulation work', wear: 'Dust mask, hand gloves' },
  { work: 'Working at height', wear: 'Full body harness, safety net, lifeline, fall arrestor if needed' },
  { work: 'Noisy areas - DG set, piling, compressor', wear: 'Ear plugs or ear muffs' },
  { work: 'Dusty areas', wear: 'Dust mask, safety goggles' },
]

export const PERMITS: { name: string; when: string }[] = [
  { name: 'Hot work', when: 'Welding, cutting, grinding, burning, soldering, open flame, or opening electrical equipment where gas may be present.' },
  { name: 'Work at height', when: 'Any work more than 1.8 m above the ground.' },
  { name: 'Electrical', when: 'Any work on a live electrical system.' },
  { name: 'Excavation', when: 'Any digging inside the restricted area, at any depth.' },
  { name: 'General', when: 'Other work the site team needs to authorise and control.' },
]

export const EMERGENCIES: { title: string; tone: 'danger' | 'warning' | 'info'; steps: string[]; note?: string }[] = [
  {
    title: 'Someone is hurt',
    tone: 'danger',
    steps: [
      'Tell the safety officer straight away.',
      'If the area is still dangerous, get everyone out and move the injured person to a safe place.',
      'If they cannot walk or are unconscious, do not move them without medical advice.',
      'Give first aid and call the nurse, doctor or an ambulance.',
      'Stop all work there and barricade the spot. Do not touch or move any equipment involved.',
      'Write down who saw it. The safety officer records it as an incident.',
    ],
    note: 'More than 3 days off work: notify at once. Anything more serious: phone the Safety Department immediately and send a written report within 7 days.',
  },
  {
    title: 'There is a fire',
    tone: 'warning',
    steps: [
      'Shout “Fire! Fire! Fire!” and sound the siren.',
      'Tell the safety officer or supervisor where it is and what is burning.',
      'Switch off electrical equipment and engines. Close gas cylinders.',
      'Fight it only if it is small, with the right extinguisher. Otherwise get out.',
      'Clear the road. One person waits at the gate to guide the fire brigade.',
      'Go by the shortest way to the assembly point.',
    ],
  },
  {
    title: 'The siren sounds',
    tone: 'info',
    steps: [
      'A long, continuous siren means leave the site.',
      'Switch off what you are using and close gas cylinders. Lower booms and forks.',
      'Make sure the people near you have heard it.',
      'Leave your belongings. Walk calmly to the assembly point.',
      'Stay there until the head count is done. Supervisors count their people.',
      'A broken, on-off siren means it is safe to go back to work.',
    ],
  },
]

export const ROLES: { who: string; does: string[] }[] = [
  { who: 'Project Manager', does: ['Makes sure subcontractors follow this plan and the BOCW rules', 'Takes action when safety rules are broken'] },
  { who: 'Construction Manager', does: ['In overall charge of site safety', 'Uses only competent people and removes anyone who refuses the rules', 'Stops work in an unsafe area and reports every accident at once'] },
  { who: 'Safety Manager', does: ['Inspects the site and checks work plans before work starts', 'Investigates every incident and stops high-risk work'] },
  { who: 'Safety Supervisor / Officer', does: ['Patrols the site every day', 'Checks subcontractors’ methods and reports anything that needs stopping'] },
  { who: 'Project Nurse', does: ['On site full time', 'Treats injuries, keeps the record and runs the hygiene programme'] },
  { who: 'Every worker', does: ['Follows the rules and looks after their PPE', 'Attends toolbox talks, keeps the workplace tidy, reports defects and injuries'] },
]

export const CHECKS: { when: string; what: string }[] = [
  { when: 'Every day', what: 'Site inspection before work starts, by engineers, supervisors and safety officers. Serious findings go to the Construction Manager.' },
  { when: 'Every week', what: 'Safety patrol by the safety team. Safety nets inspected.' },
  { when: 'Every month', what: 'Safety audit with a written report and action plan. First aid kits checked and expired items replaced.' },
  { when: 'Every quarter', what: 'Fire extinguishers inspected by the supplier and entered in the logbook.' },
  { when: 'Before use', what: 'Scaffolds tagged green (safe) or red (unsafe). Cranes and lifting gear checked against the checklist.' },
]

export const TOPICS: { title: string; ref: string; points: string[] }[] = [
  { title: 'Working at height and scaffolding', ref: '9.2, 11', points: [
    'Get a height permit before work above 1.8 m. Scaffolds are certified by the safety team.',
    'Working platform at least 0.7 m wide, toe boards at least 0.15 m high, with handrails.',
    'Gap between scaffold and wall no more than 20 cm.',
    'Never throw tools or scaffold parts up or down.',
    'Guard rails: top rail at about 1.1 m, mid rail at about 0.53 m, posts no more than 2.5 m apart.',
    'No material stored within 1.8 m of a roof edge. Close or barricade every roof opening.',
  ] },
  { title: 'Ladders', ref: '16', points: [
    'Ladders are for getting up and down, not for working from.',
    'Stand it on firm, level ground: 1 m out for every 4 m up, and 1 m past the landing.',
    'Tie it, or have someone hold the bottom.',
    'Carry tools in a belt or pouch, not in your hands.',
    'On a step ladder, never stand on the top two steps. Always face the ladder.',
  ] },
  { title: 'Excavation', ref: '10', points: [
    'Check the drawings for buried cables and pipes before digging.',
    'Slope the sides at least 1:1, with a 0.5 m step for every 1.5 m of depth (except hard rock).',
    'Keep the dug soil at least 1 m back from the edge.',
    'Barricades and warning lights 1 m from the edge. Vehicles stay 2 m back.',
    'Deeper than 1.5 m: two ladders or ramps in and out.',
    'Check it every day. Stop all work if the side caves in or slides. Keep pumps ready for water.',
  ] },
  { title: 'Lifting and cranes', ref: '12', points: [
    'Crane on firm, level ground with outriggers fully out.',
    'Never lift more than the safe working load.',
    'Nobody stands under the load or the boom.',
    'One trained signaller - but anyone may give the stop signal.',
    'Use tag lines on big loads. Keep well clear of power lines. Never drag a load.',
    'At the end of the day, take the load off and raise the hook.',
  ] },
  { title: 'Electrical safety', ref: '9.3.7', points: [
    'Only an experienced electrician does temporary wiring.',
    'All distribution boards earthed; all power tools through an ELCB.',
    'Panels 50 cm above the ground and covered.',
    'Cables off walkways, and protected where vehicles cross.',
    'Lock out and tag before working on any equipment.',
  ] },
  { title: 'Fire prevention and gas cylinders', ref: '9.3', points: [
    'Oxygen and acetylene stored apart, upright and chained, at least 6 m from buildings and fuel.',
    'Flashback arrestors on cutting torches. Valve caps on when not in use.',
    'Fire extinguishers (ABC type) numbered, logged, and inspected every quarter.',
    'No burning of rubbish on site. “No smoking” signs where needed.',
    'Do not keep oily rags or jute bags together - they can catch fire on their own.',
  ] },
  { title: 'Hand and power tools', ref: '9.4', points: [
    'Use the right tool for the job. Replace cracked or loose handles.',
    'Grinder guard always on. Check the wheel’s rpm rating and expiry date.',
    'Unplug before changing a wheel or repairing a tool.',
    'Never point compressed air at yourself or others.',
    'Do not carry sharp tools in your pockets or throw tools.',
  ] },
  { title: 'Vehicles on site', ref: '5.7', points: [
    '20 km/h, marked routes only, seat belts on, driving licence carried.',
    'No people carried in trucks or trailers. No more passengers than seats.',
    'Never overload. Red flag on overhanging loads by day, a light by night.',
    'Park only in marked places. Lower a tipper body before driving off.',
    'No refuelling inside restricted areas.',
  ] },
  { title: 'Housekeeping', ref: '6', points: [
    'Keep your work area clean during and after the work.',
    'Remove planks with nails and any sharp objects at once.',
    'Cables laid so nobody trips; overhead cables high enough for vehicles.',
    'Platforms, scaffolds and stairs kept free of debris. Shuttering stacked neatly.',
    'Never block extinguishers, hydrants, valves or emergency exits.',
  ] },
  { title: 'Chemicals and hazardous substances', ref: '13', points: [
    'Read the safety data sheet (MSDS) before using a chemical.',
    'Use the safest form available, with good ventilation.',
    'Store chemicals labelled, and keep those that react with each other apart.',
    'Drip trays at every fuel and oil filling point.',
  ] },
  { title: 'Hot weather', ref: '17', points: [
    'Drink about two glasses of water before starting, then a small cup every 15 to 20 minutes.',
    'Avoid alcohol, coffee, tea and fizzy drinks with caffeine.',
    'Light-coloured, loose clothes. A hat outside.',
    'Take breaks in the shade. Work at a steady pace.',
    'Dizzy, sick or confused? Tell your supervisor at once - and watch out for each other.',
  ] },
  { title: 'Environment and waste', ref: '15', points: [
    'Spray water to keep dust down.',
    'Sort waste into the blue, green, red and yellow bins - metal, non-metal and oily kept apart.',
    'Never pour oil or liquid waste on the ground or into drains.',
    'Septic tanks cleaned regularly.',
  ] },
  { title: 'Visitors and security', ref: '7', points: [
    'Every visitor reports to the site office first.',
    'Only people with business on site are let in.',
    'Visitors without site work sign a release before going further than the office.',
    'Everyone is briefed on safety before entering the work area.',
  ] },
  { title: 'Training', ref: '5.1', points: [
    'Induction for every worker before their first day.',
    'Toolbox talks on the hazards of each job.',
    'Training in HSE rules, PPE, permits, heavy plant, firefighting and emergencies.',
    'Plus electrical safety, scaffolding, first aid and material handling.',
  ] },
]
