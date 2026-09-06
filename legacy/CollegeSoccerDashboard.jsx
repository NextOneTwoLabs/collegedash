import { useState, useMemo, useCallback } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Legend, LineChart, Line } from "recharts";

// ─── SCHOOL DATA ─────────────────────────────────────────────────────────────
const SCHOOLS = [
  {
    id: "unc",
    name: "University of North Carolina",
    nickname: "Tar Heels",
    conference: "ACC",
    city: "Chapel Hill", state: "NC", region: "Southeast",
    colors: ["#7BAFD4", "#13294B"],
    historicalRecord: { wins: 920, losses: 65, draws: 48, winPct: .914 },
    nationalTitles: 23,
    titleYears: "1982–94 (12), 1996–97, 1999–2000, 2003, 2006, 2008–09, 2012, 2024",
    ncaaTourneyApps: 38,
    confTitles: 24,
    recentRankings: [{ yr: 2025, rk: 3 }, { yr: 2024, rk: 1 }, { yr: 2023, rk: 4 }],
    headCoach: "Damon Nahas",
    coachTenure: "2025–present",
    coachRecord: "First season (Won 2024 title as interim)",
    coachPhilosophy: "High-pressing, possession-oriented attacking play — continuation of the legendary Dorrance system",
    coachHighlights: ["Won 2024 NCAA Championship as interim HC", "Named permanent head coach Dec 2024", "Succeeded Anson Dorrance (22 titles, 1979–2024)"],
    famousAlumni: [
      { name: "Mia Hamm", note: "2x World Cup, 2x Olympic gold, all-time great" },
      { name: "Crystal Dunn", note: "USWNT, NWSL star, World Cup winner" },
      { name: "Tobin Heath", note: "2x World Cup champion, Olympic gold" },
      { name: "Heather O'Reilly", note: "3x Olympic gold, World Cup winner" }
    ],
    keyPlayers: ["Ally Sentnor (F)", "Tessa Dellarose (M)", "Avery Patterson (D)"],
    playStyle: "High-tempo attacking, relentless pressing, deep talent pool. The gold standard of college soccer.",
    reputation: "The most dominant program in history — 23 national titles. Unmatched legacy and pipeline to NWSL/USWNT.",
    rivalries: ["Duke (Tobacco Road)", "Virginia (ACC)"],
    academicRank: 22,
    notablePrograms: ["Business (Kenan-Flagler)", "Journalism", "Public Health", "Computer Science"],
    gradRate: 97,
    athleteSupport: "Elite academic center for athletes, dedicated tutoring, career services",
    scholarships: 14,
    facilityQuality: "Elite",
    facilities: "Dorrance Field (5,000 cap), Carmichael Arena weight room, sports medicine complex",
    climate: "Humid subtropical — warm springs/falls, mild winters, hot summers",
    campusVibe: "Classic Southern college town with strong athletic culture and passionate fan base",
    surroundingArea: "Charming downtown Chapel Hill, Research Triangle (Raleigh-Durham 30 min)",
    fitScores: { athletic: 99, academic: 90, location: 82, resources: 95 }
  },
  {
    id: "stanford",
    name: "Stanford University",
    nickname: "Cardinal",
    conference: "ACC",
    city: "Stanford", state: "CA", region: "West",
    colors: ["#8C1515", "#FFFFFF"],
    historicalRecord: { wins: 590, losses: 72, draws: 41, winPct: .869 },
    nationalTitles: 3,
    titleYears: "2011, 2017, 2019",
    ncaaTourneyApps: 30,
    confTitles: 12,
    recentRankings: [{ yr: 2025, rk: 2 }, { yr: 2024, rk: 2 }, { yr: 2023, rk: 2 }],
    headCoach: "Paul Ratcliffe",
    coachTenure: "2003–present (23rd season)",
    coachRecord: "392-72-41 (.817)",
    coachPhilosophy: "Technical precision, intelligent possession, tactical flexibility",
    coachHighlights: ["3 NCAA Championships", "12 Conference titles", "62-15-6 in NCAA tournament"],
    famousAlumni: [
      { name: "Christen Press", note: "USWNT, 2x World Cup champion" },
      { name: "Kelley O'Hara", note: "USWNT, 2x World Cup winner, Olympic gold" },
      { name: "Julie Ertz", note: "2x World Cup champion, NWSL MVP" },
      { name: "Tierna Davidson", note: "USWNT, NWSL defender" }
    ],
    keyPlayers: ["Andrea Kitahata (M)", "Jasmine Aikey (F)", "Haley Craig (GK)"],
    playStyle: "Technically brilliant, patient build-up, smart positional play. Recruits elite two-way athletes.",
    reputation: "Perennial contender — 3 titles and consistent College Cup runs. Best combo of athletics and academics.",
    rivalries: ["Cal Berkeley (Bay Area)", "UCLA (Pac-12/ACC)"],
    academicRank: 3,
    notablePrograms: ["Computer Science", "Engineering", "Business (GSB)", "Medicine"],
    gradRate: 98,
    athleteSupport: "World-class athlete development, Silicon Valley networking, career mentorship",
    scholarships: 14,
    facilityQuality: "Elite",
    facilities: "Laird Q. Cagan Stadium (4,000 cap), top-tier training center, sports science lab",
    climate: "Mediterranean — dry warm summers, mild rainy winters, year-round pleasant",
    campusVibe: "Innovation-driven, beautiful palm-lined campus, entrepreneurial energy",
    surroundingArea: "Silicon Valley, 35 min to San Francisco, Palo Alto downtown",
    fitScores: { athletic: 96, academic: 99, location: 92, resources: 98 }
  },
  {
    id: "fsu",
    name: "Florida State University",
    nickname: "Seminoles",
    conference: "ACC",
    city: "Tallahassee", state: "FL", region: "Southeast",
    colors: ["#782F40", "#CEB888"],
    historicalRecord: { wins: 580, losses: 90, draws: 55, winPct: .838 },
    nationalTitles: 5,
    titleYears: "2014, 2018, 2021, 2023, 2025",
    ncaaTourneyApps: 28,
    confTitles: 10,
    recentRankings: [{ yr: 2025, rk: 1 }, { yr: 2024, rk: 5 }, { yr: 2023, rk: 1 }],
    headCoach: "Brian Pensky",
    coachTenure: "2022–present (4th season)",
    coachRecord: "54-5-8 at FSU (.906)",
    coachPhilosophy: "Aggressive attacking, organized defense, culture of winning mentality",
    coachHighlights: ["2 NCAA titles in 3 years (2023, 2025)", "22-0-1 undefeated season 2023", "National Coaching Staff of the Year 2025"],
    famousAlumni: [
      { name: "Deyna Castellanos", note: "Venezuela captain, Atlético Madrid star" },
      { name: "Megan Campbell", note: "Ireland international" },
      { name: "Kristin Hamilton", note: "All-American, NWSL" }
    ],
    keyPlayers: ["Wrianna Hudson (F)", "Beata Olsson (M)", "Ran Iwai (D)"],
    playStyle: "Aggressive, high-pressing, direct attacking with lethal finishing. Dominant defensive structure.",
    reputation: "Current dynasty — 5 titles including 2 of last 3. The hottest program in the country right now.",
    rivalries: ["Florida (in-state)", "Miami (ACC)"],
    academicRank: 55,
    notablePrograms: ["Film & Creative Writing", "Criminology", "Music", "Business"],
    gradRate: 93,
    athleteSupport: "Comprehensive student-athlete services, NIL support, academic advising",
    scholarships: 14,
    facilityQuality: "Elite",
    facilities: "Seminole Soccer Complex (3,500 cap), indoor training facility, state-of-art weight room",
    climate: "Humid subtropical — hot summers, warm winters, afternoon thunderstorms",
    campusVibe: "Passionate athletic culture, massive school spirit, vibrant social scene",
    surroundingArea: "State capital, 4.5 hrs to beaches, Southern college town feel",
    fitScores: { athletic: 99, academic: 72, location: 75, resources: 92 }
  },
  {
    id: "ucla",
    name: "UCLA",
    nickname: "Bruins",
    conference: "Big Ten",
    city: "Los Angeles", state: "CA", region: "West",
    colors: ["#2774AE", "#FFD100"],
    historicalRecord: { wins: 540, losses: 95, draws: 50, winPct: .824 },
    nationalTitles: 1,
    titleYears: "2022",
    ncaaTourneyApps: 26,
    confTitles: 8,
    recentRankings: [{ yr: 2025, rk: 12 }, { yr: 2024, rk: 8 }, { yr: 2023, rk: 6 }],
    headCoach: "Gof Boyoko",
    coachTenure: "2026–present (incoming)",
    coachRecord: "First season at UCLA",
    coachPhilosophy: "Dynamic attacking play with emphasis on player development and tactical adaptability",
    coachHighlights: ["Succeeded Margueritte Aozasa (67-13-9, won 2022 title)", "First D1 female coach of color to win NCAA title (Aozasa)"],
    famousAlumni: [
      { name: "Mallory Swanson (née Pugh)", note: "USWNT star, Olympic gold, NWSL MVP" },
      { name: "Jessie Fleming", note: "Canada international, Olympic gold medalist" },
      { name: "Karina Rodriguez", note: "Mexico international" }
    ],
    keyPlayers: ["Reilyn Turner (F)", "Sunshine Fontes (M)", "Lilly Reale (D)"],
    playStyle: "Skillful, creative, West Coast flair — technical players who love the ball at their feet.",
    reputation: "Historically strong, won 2022 title under trailblazing coach. Transition year with new coaching staff.",
    rivalries: ["USC (crosstown)", "Cal Berkeley (UC system)"],
    academicRank: 15,
    notablePrograms: ["Film/TV", "Engineering", "Psychology", "Political Science"],
    gradRate: 95,
    athleteSupport: "Excellent academic support, career development, mental health resources",
    scholarships: 14,
    facilityQuality: "Excellent",
    facilities: "Wallis Annenberg Stadium (5,000 cap), UCLA Athletic Performance Center",
    climate: "Mediterranean — sunny year-round, mild winters, warm dry summers",
    campusVibe: "Vibrant campus in Westwood, diverse community, strong school pride",
    surroundingArea: "Los Angeles — beaches, entertainment, culture, Westwood Village",
    fitScores: { athletic: 88, academic: 88, location: 95, resources: 90 }
  },
  {
    id: "virginia",
    name: "University of Virginia",
    nickname: "Cavaliers",
    conference: "ACC",
    city: "Charlottesville", state: "VA", region: "Mid-Atlantic",
    colors: ["#232D4B", "#F84C1E"],
    historicalRecord: { wins: 620, losses: 110, draws: 52, winPct: .826 },
    nationalTitles: 7,
    titleYears: "1991, 1993, 1994, 2004, 2009, 2012, 2014",
    ncaaTourneyApps: 33,
    confTitles: 14,
    recentRankings: [{ yr: 2025, rk: 3 }, { yr: 2024, rk: 7 }, { yr: 2023, rk: 8 }],
    headCoach: "Steve Swanson",
    coachTenure: "2000–present (26th season)",
    coachRecord: "380-90-40 (.784)",
    coachPhilosophy: "Balanced, disciplined play — strong defensively with creative attack from midfield",
    coachHighlights: ["4 NCAA Championships at UVA", "14 ACC titles", "Consistent top-10 program"],
    famousAlumni: [
      { name: "Emily Sonnett", note: "USWNT, NWSL All-Star defender" },
      { name: "Becky Sauerbrunn", note: "USWNT captain, 2x World Cup winner" },
      { name: "Morgan Brian", note: "World Cup winner, NWSL star" }
    ],
    keyPlayers: ["Alexis Spaanstra (F)", "Lia Godfrey (M)", "Samar Guidry (D)"],
    playStyle: "Disciplined, tactical, organized defense-first approach with lethal counter-attacks.",
    reputation: "Blue-blood program — 7 titles, consistent ACC contender. Strong development pipeline.",
    rivalries: ["Virginia Tech (in-state)", "North Carolina (ACC)"],
    academicRank: 24,
    notablePrograms: ["Business (Darden)", "Law", "Engineering", "Government"],
    gradRate: 97,
    athleteSupport: "Dedicated academic advisors for athletes, tutoring center, career planning",
    scholarships: 14,
    facilityQuality: "Excellent",
    facilities: "Klöckner Stadium (4,000 cap), dedicated soccer training fields, McCue Center",
    climate: "Humid subtropical — beautiful fall foliage, moderate winters, warm summers",
    campusVibe: "Historic Jeffersonian campus, intellectual culture, tight-knit community",
    surroundingArea: "Blue Ridge Mountains, wine country, charming downtown Charlottesville",
    fitScores: { athletic: 94, academic: 90, location: 85, resources: 88 }
  },
  {
    id: "notre-dame",
    name: "University of Notre Dame",
    nickname: "Fighting Irish",
    conference: "ACC",
    city: "Notre Dame", state: "IN", region: "Midwest",
    colors: ["#0C2340", "#C99700"],
    historicalRecord: { wins: 570, losses: 95, draws: 48, winPct: .833 },
    nationalTitles: 4,
    titleYears: "1995, 2004, 2010, 2020",
    ncaaTourneyApps: 28,
    confTitles: 9,
    recentRankings: [{ yr: 2025, rk: 1 }, { yr: 2024, rk: 6 }, { yr: 2023, rk: 10 }],
    headCoach: "Nate Norman",
    coachTenure: "2018–present (8th season)",
    coachRecord: "105-20-15 (.804)",
    coachPhilosophy: "Attacking mindset, high intensity, emphasis on team culture and character",
    coachHighlights: ["Beat #5 Florida State 4-2 in 2025", "Consistent top-10 finishes", "Strong recruiter"],
    famousAlumni: [
      { name: "Adriana Leon", note: "Canada international, NWSL forward" },
      { name: "Catarina Macario", note: "Brazil/USWNT, Chelsea FC" },
      { name: "Samantha Leshnak", note: "NWSL goalkeeper" }
    ],
    keyPlayers: ["Olivia Wingate (F)", "Korbin Albert (M)", "Leah Klenke (D)"],
    playStyle: "Hard-nosed, high-energy, never-quit mentality. Physical and fast with skilled attackers.",
    reputation: "Elite program with 4 titles. Known for passionate culture and turning players into pros.",
    rivalries: ["Michigan (regional)", "Stanford (historic)"],
    academicRank: 18,
    notablePrograms: ["Business (Mendoza)", "Engineering", "Pre-Law", "Architecture"],
    gradRate: 98,
    athleteSupport: "Exceptional — Guglielmino Athletics Complex, dedicated academic services",
    scholarships: 14,
    facilityQuality: "Elite",
    facilities: "Alumni Stadium (3,000 cap), Guglielmino Complex, indoor practice facility",
    climate: "Continental — cold winters with snow, pleasant falls, warm summers",
    campusVibe: "Iconic campus, deep traditions, strong Catholic identity, legendary athletics",
    surroundingArea: "South Bend — small city, 90 min to Chicago, college-town atmosphere",
    fitScores: { athletic: 95, academic: 92, location: 72, resources: 95 }
  },
  {
    id: "duke",
    name: "Duke University",
    nickname: "Blue Devils",
    conference: "ACC",
    city: "Durham", state: "NC", region: "Southeast",
    colors: ["#003087", "#FFFFFF"],
    historicalRecord: { wins: 460, losses: 120, draws: 55, winPct: .768 },
    nationalTitles: 1,
    titleYears: "2009",
    ncaaTourneyApps: 22,
    confTitles: 5,
    recentRankings: [{ yr: 2025, rk: 4 }, { yr: 2024, rk: 4 }, { yr: 2023, rk: 7 }],
    headCoach: "Kieran Hall",
    coachTenure: "2025–present (1st season)",
    coachRecord: "First season as head coach",
    coachPhilosophy: "Possession-based, creative attack, player empowerment",
    coachHighlights: ["Took over elite program at Duke", "Back-to-back College Cup appearances (2024, 2025)"],
    famousAlumni: [
      { name: "Laura Weinberg", note: "All-American, NWSL" },
      { name: "Tara Schwitter", note: "NWSL professional" },
      { name: "Kayla McCoy", note: "NWSL, All-ACC" }
    ],
    keyPlayers: ["Michelle Cooper (F)", "Olivia Migli (M)", "Delaney Tauzel (D)"],
    playStyle: "Technical, possession-heavy, creative midfield play. Emphasizes intelligence on the ball.",
    reputation: "Rising power — College Cup in 2024 & 2025. Academic prestige meets athletic ambition.",
    rivalries: ["UNC (Tobacco Road)", "Wake Forest (ACC)"],
    academicRank: 7,
    notablePrograms: ["Public Policy", "Medicine", "Engineering", "Economics"],
    gradRate: 98,
    athleteSupport: "Outstanding — dedicated athlete academic advisors, mental health support",
    scholarships: 14,
    facilityQuality: "Excellent",
    facilities: "Koskinen Stadium (4,000 cap), Pascal Field House, Duke Sports Sciences Institute",
    climate: "Humid subtropical — warm falls, mild winters, hot summers",
    campusVibe: "Gothic architecture, intense academics, strong basketball culture lifting all sports",
    surroundingArea: "Durham/Research Triangle, vibrant food scene, growing tech hub",
    fitScores: { athletic: 88, academic: 96, location: 82, resources: 90 }
  },
  {
    id: "penn-state",
    name: "Penn State University",
    nickname: "Nittany Lions",
    conference: "Big Ten",
    city: "State College", state: "PA", region: "Northeast",
    colors: ["#041E42", "#FFFFFF"],
    historicalRecord: { wins: 530, losses: 100, draws: 55, winPct: .814 },
    nationalTitles: 2,
    titleYears: "2015, 2016",
    ncaaTourneyApps: 27,
    confTitles: 11,
    recentRankings: [{ yr: 2025, rk: 11 }, { yr: 2024, rk: 9 }, { yr: 2023, rk: 12 }],
    headCoach: "Erica Dambach",
    coachTenure: "2007–present (19th season)",
    coachRecord: "290-55-32 (.812)",
    coachPhilosophy: "Competitive excellence, high fitness, direct attacking with width",
    coachHighlights: ["2 NCAA Championships (back-to-back 2015, 2016)", "11 Big Ten titles", "Most winning coach in PSU history"],
    famousAlumni: [
      { name: "Ali Krieger", note: "USWNT, World Cup & Olympic champion" },
      { name: "Alyssa Naeher", note: "USWNT goalkeeper, World Cup winner" },
      { name: "Raquel Rodriguez", note: "Costa Rica captain, NWSL" }
    ],
    keyPlayers: ["Ally Schlegel (F)", "Amelia White (M)", "Kerry Abello (D)"],
    playStyle: "Physical, high-energy, direct play with an emphasis on fitness and set pieces.",
    reputation: "Big Ten powerhouse — 2 titles, consistently in NCAA tournament. Massive school support.",
    rivalries: ["Ohio State (Big Ten)", "Rutgers (regional)"],
    academicRank: 60,
    notablePrograms: ["Engineering", "Business (Smeal)", "Kinesiology", "Communications"],
    gradRate: 94,
    athleteSupport: "Morgan Academic Center, comprehensive athlete support services",
    scholarships: 14,
    facilityQuality: "Excellent",
    facilities: "Jeffrey Field (5,000 cap), Lasch Football Building weight room, Pegula Ice Arena area",
    climate: "Continental — cold snowy winters, crisp falls, warm summers",
    campusVibe: "Quintessential big-school spirit, Happy Valley, massive gameday atmosphere",
    surroundingArea: "State College — true college town, Appalachian foothills, nature access",
    fitScores: { athletic: 90, academic: 76, location: 68, resources: 88 }
  },
  {
    id: "santa-clara",
    name: "Santa Clara University",
    nickname: "Broncos",
    conference: "WCC",
    city: "Santa Clara", state: "CA", region: "West",
    colors: ["#862633", "#FFFFFF"],
    historicalRecord: { wins: 510, losses: 120, draws: 60, winPct: .783 },
    nationalTitles: 2,
    titleYears: "2001, 2020",
    ncaaTourneyApps: 24,
    confTitles: 15,
    recentRankings: [{ yr: 2025, rk: 15 }, { yr: 2024, rk: 14 }, { yr: 2023, rk: 16 }],
    headCoach: "Jerry Smith",
    coachTenure: "1987–present (39th season)",
    coachRecord: "510-120-60 (.783)",
    coachPhilosophy: "Technical mastery, creative freedom, player-centered development",
    coachHighlights: ["Longest-tenured D1 women's soccer coach", "2 NCAA Championships", "15 WCC titles"],
    famousAlumni: [
      { name: "Brandi Chastain", note: "USWNT legend, World Cup iconic moment" },
      { name: "Danielle Slaton", note: "USWNT, Olympic medalist" },
      { name: "Julie Johnston Ertz", note: "Played at SCU before transferring" }
    ],
    keyPlayers: ["Izzy D'Aquila (F)", "Kelsey Turnbow (M)", "Leah Preciado (D)"],
    playStyle: "Technically polished, free-flowing attack. West Coast style with emphasis on skill and creativity.",
    reputation: "Quiet powerhouse — smaller school, big results. Amazing player development track record.",
    rivalries: ["BYU (WCC)", "Portland (WCC)"],
    academicRank: 55,
    notablePrograms: ["Business (Leavey)", "Engineering", "Ethics/Jesuit tradition"],
    gradRate: 96,
    athleteSupport: "Small school advantage — personalized attention, tight community",
    scholarships: 14,
    facilityQuality: "Good",
    facilities: "Stevens Stadium (6,800 cap), dedicated training pitch, Leavey Center",
    climate: "Mediterranean — sunny, dry summers, mild wet winters, ideal for soccer",
    campusVibe: "Small Jesuit university, tight-knit, Silicon Valley location",
    surroundingArea: "Heart of Silicon Valley, 45 min to SF, tech industry opportunities",
    fitScores: { athletic: 82, academic: 80, location: 90, resources: 75 }
  },
  {
    id: "georgetown",
    name: "Georgetown University",
    nickname: "Hoyas",
    conference: "Big East",
    city: "Washington", state: "DC", region: "Mid-Atlantic",
    colors: ["#041E42", "#8D817B"],
    historicalRecord: { wins: 380, losses: 130, draws: 50, winPct: .723 },
    nationalTitles: 0,
    titleYears: "—",
    ncaaTourneyApps: 18,
    confTitles: 6,
    recentRankings: [{ yr: 2025, rk: 7 }, { yr: 2024, rk: 12 }, { yr: 2023, rk: 15 }],
    headCoach: "Dave Nolan",
    coachTenure: "2005–present (21st season)",
    coachRecord: "275-90-40 (.729)",
    coachPhilosophy: "Organized defensive structure, intelligent build-up, clinical finishing",
    coachHighlights: ["Consistent Big East contender", "Multiple Sweet 16 appearances", "Top recruiter in DC area"],
    famousAlumni: [
      { name: "Rachel Daly", note: "England international, Aston Villa, World Cup" },
      { name: "Crystal Thomas", note: "NWSL professional" }
    ],
    keyPlayers: ["Kylie Doughty (F)", "Eliza Turner (M)", "Maya Gupta (D)"],
    playStyle: "Disciplined, defensively sound, transition-based attack. Gritty and hard to beat.",
    reputation: "Rising contender — ranked #7 in 2025. Elite academics with growing soccer stature.",
    rivalries: ["Villanova (Big East)", "Providence (Big East)"],
    academicRank: 22,
    notablePrograms: ["Foreign Service (SFS)", "Government", "Business (McDonough)", "Law"],
    gradRate: 97,
    athleteSupport: "Excellent — small class sizes, dedicated academic counselors",
    scholarships: 14,
    facilityQuality: "Good",
    facilities: "Shaw Field (2,500 cap), Yates Field House, campus training center",
    climate: "Humid subtropical — hot humid summers, mild to cold winters, beautiful springs",
    campusVibe: "Historic Georgetown neighborhood, political culture, Jesuit values",
    surroundingArea: "Washington D.C. — internships, culture, museums, vibrant nightlife",
    fitScores: { athletic: 80, academic: 94, location: 95, resources: 78 }
  },
  {
    id: "michigan",
    name: "University of Michigan",
    nickname: "Wolverines",
    conference: "Big Ten",
    city: "Ann Arbor", state: "MI", region: "Midwest",
    colors: ["#00274C", "#FFCB05"],
    historicalRecord: { wins: 400, losses: 150, draws: 55, winPct: .707 },
    nationalTitles: 0,
    titleYears: "—",
    ncaaTourneyApps: 16,
    confTitles: 3,
    recentRankings: [{ yr: 2025, rk: 18 }, { yr: 2024, rk: 20 }, { yr: 2023, rk: 22 }],
    headCoach: "Jennifer Klein",
    coachTenure: "2018–present (8th season)",
    coachRecord: "85-32-18 (.696)",
    coachPhilosophy: "Possession-oriented, building from the back, developing complete players",
    coachHighlights: ["Elevated Michigan into consistent Big Ten contender", "Strong recruiting classes"],
    famousAlumni: [
      { name: "Meghan Klingenberg", note: "USWNT, World Cup winner, NWSL" },
      { name: "Nkem Ezurike", note: "NWSL professional" }
    ],
    keyPlayers: ["Sammi Woods (F)", "Katherine Smith (M)", "Hillary Beall (D)"],
    playStyle: "Athletic, competitive, build-up play from the back with pace on the counter.",
    reputation: "Big Ten competitor — improving year over year. Massive brand and resources.",
    rivalries: ["Ohio State (Big Ten)", "Michigan State (in-state)"],
    academicRank: 21,
    notablePrograms: ["Engineering", "Business (Ross)", "Computer Science", "Medicine"],
    gradRate: 96,
    athleteSupport: "Academic Success Program, career center, extensive athlete resources",
    scholarships: 14,
    facilityQuality: "Excellent",
    facilities: "U-M Soccer Stadium (3,500 cap), Junge Center, Schembechler Hall",
    climate: "Continental — cold snowy winters, warm summers, stunning fall colors",
    campusVibe: "Iconic college experience, massive school spirit, vibrant Ann Arbor",
    surroundingArea: "Ann Arbor — charming college city, 45 min to Detroit, great food/arts scene",
    fitScores: { athletic: 78, academic: 90, location: 80, resources: 90 }
  },
  {
    id: "usc",
    name: "University of Southern California",
    nickname: "Trojans",
    conference: "Big Ten",
    city: "Los Angeles", state: "CA", region: "West",
    colors: ["#990000", "#FFC72C"],
    historicalRecord: { wins: 420, losses: 130, draws: 50, winPct: .742 },
    nationalTitles: 2,
    titleYears: "2007, 2016",
    ncaaTourneyApps: 20,
    confTitles: 5,
    recentRankings: [{ yr: 2025, rk: 20 }, { yr: 2024, rk: 18 }, { yr: 2023, rk: 14 }],
    headCoach: "Jane Alukonis",
    coachTenure: "2022–present (4th season)",
    coachRecord: "35-15-8 (.672)",
    coachPhilosophy: "High-energy attacking, building a winning culture, recruiting top CA talent",
    coachHighlights: ["Rebuilding USC soccer program", "Strong Southern California recruiting pipeline"],
    famousAlumni: [
      { name: "Alex Morgan", note: "USWNT legend, 2x World Cup winner (transferred from Cal)" },
      { name: "Samantha Mewis", note: "USWNT, World Cup champion" },
      { name: "Nikki Marshall", note: "WPS/NWSL professional" }
    ],
    keyPlayers: ["Penelope Hocking (F)", "Croix Bethune (M)", "Simone Jackson (D)"],
    playStyle: "Energetic, attacking, Southern California flair — speed and creativity on the wings.",
    reputation: "2 titles but in a rebuilding phase. Massive resources and LA recruiting advantage.",
    rivalries: ["UCLA (crosstown — El Tráfico)", "Cal Berkeley"],
    academicRank: 28,
    notablePrograms: ["Film (Cinematic Arts)", "Business (Marshall)", "Engineering", "Communications"],
    gradRate: 95,
    athleteSupport: "Trojans Advantage program, academic center, career services",
    scholarships: 14,
    facilityQuality: "Excellent",
    facilities: "McAlister Field (3,500 cap), Lyon Center, Galen Center area",
    climate: "Mediterranean — sunny 300+ days/yr, mild winters, warm dry summers",
    campusVibe: "Hollywood-adjacent glamour, diverse campus, massive alumni network",
    surroundingArea: "Los Angeles — beaches, entertainment, culture, endless opportunities",
    fitScores: { athletic: 82, academic: 85, location: 96, resources: 88 }
  },
  {
    id: "wisconsin",
    name: "University of Wisconsin",
    nickname: "Badgers",
    conference: "Big Ten",
    city: "Madison", state: "WI", region: "Midwest",
    colors: ["#C5050C", "#FFFFFF"],
    historicalRecord: { wins: 350, losses: 160, draws: 60, winPct: .667 },
    nationalTitles: 0,
    titleYears: "—",
    ncaaTourneyApps: 14,
    confTitles: 2,
    recentRankings: [{ yr: 2025, rk: 16 }, { yr: 2024, rk: 22 }, { yr: 2023, rk: 25 }],
    headCoach: "Paula Wilkins",
    coachTenure: "2008–present (18th season)",
    coachRecord: "180-95-30 (.639)",
    coachPhilosophy: "Work ethic, competitive mindset, organized play on both sides of the ball",
    coachHighlights: ["Elevated Wisconsin into consistent NCAA tournament team", "2 Big Ten titles"],
    famousAlumni: [
      { name: "Rose Lavelle", note: "USWNT star, World Cup Golden Ball winner" },
      { name: "Kelley O'Hara (youth)", note: "Trained in WI system" }
    ],
    keyPlayers: ["Cameron Murtha (F)", "Maia Richters (M)", "Maia Richters (D)"],
    playStyle: "Hard-working, organized, competitive Big Ten style. Tough to break down.",
    reputation: "Solid mid-tier Big Ten program with improving trajectory. Rose Lavelle put them on the map.",
    rivalries: ["Minnesota (Big Ten border)", "Iowa (Big Ten)"],
    academicRank: 38,
    notablePrograms: ["Business", "Engineering", "Computer Science", "Dairy Science"],
    gradRate: 93,
    athleteSupport: "Academic support center, tutoring, career development",
    scholarships: 14,
    facilityQuality: "Good",
    facilities: "McClimon Soccer Complex (3,000 cap), training fields, Camp Randall area facilities",
    climate: "Continental — cold snowy winters, warm humid summers, gorgeous falls",
    campusVibe: "Lakeside campus, vibrant college town, strong school pride and tailgate culture",
    surroundingArea: "Madison — one of America's best college towns, State Street, lakes, craft beer",
    fitScores: { athletic: 74, academic: 82, location: 78, resources: 80 }
  },
  {
    id: "colorado",
    name: "University of Colorado",
    nickname: "Buffaloes",
    conference: "Big 12",
    city: "Boulder", state: "CO", region: "West",
    colors: ["#CFB87C", "#000000"],
    historicalRecord: { wins: 320, losses: 170, draws: 55, winPct: .637 },
    nationalTitles: 0,
    titleYears: "—",
    ncaaTourneyApps: 12,
    confTitles: 3,
    recentRankings: [{ yr: 2025, rk: 10 }, { yr: 2024, rk: 15 }, { yr: 2023, rk: 20 }],
    headCoach: "Danny Sanchez",
    coachTenure: "2012–present (14th season)",
    coachRecord: "145-75-25 (.643)",
    coachPhilosophy: "Possession-based, attacking mentality, developing complete student-athletes",
    coachHighlights: ["Elevated CU from mid-pack to top-10 program", "3 conference titles", "Strong upward trajectory"],
    famousAlumni: [
      { name: "Lindsey Horan", note: "USWNT captain, Lyon/OL Reign, World Cup" },
      { name: "Danica Evans", note: "NWSL professional" }
    ],
    keyPlayers: ["Shyra James (F)", "Civana Kuhlmann (M)", "Jade Ruiters (D)"],
    playStyle: "Possession-focused, high-altitude pressing, athletic and relentless work rate.",
    reputation: "One of the fastest-rising programs — ranked #10 in 2025. Great location recruiter.",
    rivalries: ["Colorado State (in-state)", "Utah (Big 12)"],
    academicRank: 105,
    notablePrograms: ["Aerospace Engineering", "Environmental Science", "Business (Leeds)", "Physics"],
    gradRate: 90,
    athleteSupport: "Academic services center, tutoring, career counseling",
    scholarships: 14,
    facilityQuality: "Good",
    facilities: "Prentup Field (3,500 cap), Champions Center, Dal Ward Center",
    climate: "Semi-arid — 300+ days of sunshine, dry cold winters, cool summers at altitude",
    campusVibe: "Outdoor-adventure culture, stunning Flatirons backdrop, healthy active lifestyle",
    surroundingArea: "Boulder — hiking, skiing, craft beer, 30 min to Denver",
    fitScores: { athletic: 78, academic: 72, location: 92, resources: 76 }
  },
  {
    id: "texas-am",
    name: "Texas A&M University",
    nickname: "Aggies",
    conference: "SEC",
    city: "College Station", state: "TX", region: "South",
    colors: ["#500000", "#FFFFFF"],
    historicalRecord: { wins: 420, losses: 135, draws: 55, winPct: .733 },
    nationalTitles: 0,
    titleYears: "—",
    ncaaTourneyApps: 18,
    confTitles: 4,
    recentRankings: [{ yr: 2025, rk: 14 }, { yr: 2024, rk: 16 }, { yr: 2023, rk: 18 }],
    headCoach: "Bobby Shuttleworth",
    coachTenure: "2026–present (incoming)",
    coachRecord: "First season as head coach",
    coachPhilosophy: "Championship-winning culture — learned under Brian Pensky at FSU",
    coachHighlights: ["Associate HC at FSU during 2023 & 2025 title runs", "Two-time national championship assistant", "Hired day after FSU won 2025 title"],
    famousAlumni: [
      { name: "Ally Watt", note: "NWSL professional, Racing Louisville" },
      { name: "Jimena Lopez", note: "Mexico international, NWSL" }
    ],
    keyPlayers: ["Maile Hayes (F)", "Barbara Olivieri (M)", "Macy Matula (D)"],
    playStyle: "Physical, aggressive SEC style with strong defensive organization.",
    reputation: "Strong SEC program with new coaching energy from FSU's championship pipeline. Could surge.",
    rivalries: ["Texas (Lone Star)", "LSU (SEC)"],
    academicRank: 47,
    notablePrograms: ["Engineering", "Agriculture", "Business (Mays)", "Veterinary Medicine"],
    gradRate: 92,
    athleteSupport: "12th Man Foundation support, academic center, career services",
    scholarships: 14,
    facilityQuality: "Excellent",
    facilities: "Ellis Field (5,000 cap), new training facility, Bright Football Complex access",
    climate: "Humid subtropical — hot humid summers, mild winters, rainy springs",
    campusVibe: "Unmatched school spirit, Aggie traditions, tight-knit military heritage",
    surroundingArea: "College Station — college town, 90 min to Houston, growing community",
    fitScores: { athletic: 80, academic: 78, location: 70, resources: 86 }
  },
  {
    id: "tennessee",
    name: "University of Tennessee",
    nickname: "Lady Volunteers",
    conference: "SEC",
    city: "Knoxville", state: "TN", region: "Southeast",
    colors: ["#FF8200", "#FFFFFF"],
    historicalRecord: { wins: 380, losses: 150, draws: 50, winPct: .699 },
    nationalTitles: 0,
    titleYears: "—",
    ncaaTourneyApps: 16,
    confTitles: 3,
    recentRankings: [{ yr: 2025, rk: 4 }, { yr: 2024, rk: 10 }, { yr: 2023, rk: 13 }],
    headCoach: "Joe Kirt",
    coachTenure: "2022–present (4th season)",
    coachRecord: "45-12-8 at Tennessee (.754)",
    coachPhilosophy: "High-energy pressing, aggressive attacking, culture of accountability",
    coachHighlights: ["Rapidly elevated Tennessee to top-5 program", "Ranked #4 in 2025", "Strong recruiter"],
    famousAlumni: [
      { name: "Alison Whitaker", note: "NWSL professional" },
      { name: "Hannah Wilkinson", note: "New Zealand international, World Cup" }
    ],
    keyPlayers: ["Jaida Thomas (F)", "Claudia Dickey (GK)", "Taylor Huff (M)"],
    playStyle: "High-pressing, direct, aggressive — SEC physicality with increasing technical quality.",
    reputation: "Rapidly rising — from mid-SEC to top-5 nationally in 3 years. Watch this program.",
    rivalries: ["Vanderbilt (in-state)", "Georgia (SEC)"],
    academicRank: 103,
    notablePrograms: ["Business (Haslam)", "Engineering", "Supply Chain Management", "Nuclear Engineering"],
    gradRate: 91,
    athleteSupport: "Thornton Athletics Student Life Center, comprehensive support",
    scholarships: 14,
    facilityQuality: "Good",
    facilities: "Regal Soccer Stadium (3,500 cap), training complex, Neyland area facilities",
    climate: "Humid subtropical — warm to hot most of year, mild winters, beautiful fall",
    campusVibe: "Passionate Vol Nation, SEC gameday culture, vibrant campus life",
    surroundingArea: "Knoxville — Great Smoky Mountains gateway, growing downtown, music scene",
    fitScores: { athletic: 84, academic: 68, location: 78, resources: 82 }
  },
  {
    id: "west-virginia",
    name: "West Virginia University",
    nickname: "Mountaineers",
    conference: "Big 12",
    city: "Morgantown", state: "WV", region: "Mid-Atlantic",
    colors: ["#002855", "#EAAA00"],
    historicalRecord: { wins: 380, losses: 145, draws: 50, winPct: .704 },
    nationalTitles: 0,
    titleYears: "—",
    ncaaTourneyApps: 16,
    confTitles: 4,
    recentRankings: [{ yr: 2025, rk: 22 }, { yr: 2024, rk: 25 }, { yr: 2023, rk: 28 }],
    headCoach: "Nikki Izzo-Brown",
    coachTenure: "1996–present (30th season)",
    coachRecord: "380-145-50 (.704)",
    coachPhilosophy: "Fundamentals, team-first mentality, developing well-rounded student-athletes",
    coachHighlights: ["Founded the program in 1996", "Only coach in program history", "4 conference titles"],
    famousAlumni: [
      { name: "Ashley Lawrence", note: "Canada international, PSG/Chelsea" },
      { name: "Kadeisha Buchanan", note: "Canada, Chelsea FC, Ballon d'Or nominee" }
    ],
    keyPlayers: ["Lily McCarthy (F)", "Alina Stahl (M)", "Jordan Brewster (D)"],
    playStyle: "Physical, competitive, never-give-up Mountaineer mentality. Strong defensive foundations.",
    reputation: "Consistent Big 12 contender with impressive international alumni pipeline (Canada national team).",
    rivalries: ["Pittsburgh (Backyard Brawl)", "Virginia Tech (regional)"],
    academicRank: 187,
    notablePrograms: ["Forensic Science", "Engineering", "Business", "Mining Engineering"],
    gradRate: 89,
    athleteSupport: "Academic support services, tutoring, career planning",
    scholarships: 14,
    facilityQuality: "Good",
    facilities: "Dick Dlesk Soccer Stadium (3,000 cap), practice complex, Coliseum area",
    climate: "Humid continental — cold winters with snow, warm summers, stunning fall foliage",
    campusVibe: "Mountain culture, passionate fans, tight-knit community, Appalachian pride",
    surroundingArea: "Morgantown — college town in the mountains, outdoor recreation, 75 min to Pittsburgh",
    fitScores: { athletic: 74, academic: 60, location: 70, resources: 72 }
  },
  {
    id: "cal-berkeley",
    name: "UC Berkeley",
    nickname: "Golden Bears",
    conference: "ACC",
    city: "Berkeley", state: "CA", region: "West",
    colors: ["#003262", "#FDB515"],
    historicalRecord: { wins: 380, losses: 155, draws: 55, winPct: .691 },
    nationalTitles: 1,
    titleYears: "2013",
    ncaaTourneyApps: 17,
    confTitles: 3,
    recentRankings: [{ yr: 2025, rk: 24 }, { yr: 2024, rk: 22 }, { yr: 2023, rk: 20 }],
    headCoach: "Neil McGuire",
    coachTenure: "2007–present (19th season)",
    coachRecord: "205-100-35 (.654)",
    coachPhilosophy: "Technical, possession-oriented, building creative players",
    coachHighlights: ["2013 NCAA Championship", "3 conference titles", "Consistent NCAA tournament presence"],
    famousAlumni: [
      { name: "Alex Morgan", note: "USWNT legend, 2x World Cup champion (left early for pro)" },
      { name: "Sydney Leroux", note: "USWNT, Olympic gold, NWSL star" }
    ],
    keyPlayers: ["Mia Fontana (F)", "Emily Smith (M)", "Angelina Anderson (D)"],
    playStyle: "Bay Area technical style — creative, possession-focused, skilled individual players.",
    reputation: "Title winner in 2013, strong public university option. Great academics + California lifestyle.",
    rivalries: ["Stanford (Big Game)", "UCLA (UC system)"],
    academicRank: 15,
    notablePrograms: ["Computer Science", "Engineering (EECS)", "Business (Haas)", "Biological Sciences"],
    gradRate: 93,
    athleteSupport: "Athletic Study Center, comprehensive tutoring, career mentorship",
    scholarships: 14,
    facilityQuality: "Good",
    facilities: "Edwards Stadium (5,000 cap), training fields, Haas Pavilion area",
    climate: "Mediterranean — dry warm summers, mild rainy winters, frequent fog",
    campusVibe: "Intellectually vibrant, diverse, activism culture, beautiful hillside campus",
    surroundingArea: "Berkeley/Bay Area — San Francisco 20 min, Silicon Valley, incredible food & culture",
    fitScores: { athletic: 76, academic: 95, location: 94, resources: 78 }
  },
  {
    id: "harvard",
    name: "Harvard University",
    nickname: "Crimson",
    conference: "Ivy League",
    city: "Cambridge", state: "MA", region: "Northeast",
    colors: ["#A51C30", "#000000"],
    historicalRecord: { wins: 310, losses: 140, draws: 45, winPct: .672 },
    nationalTitles: 0,
    titleYears: "—",
    ncaaTourneyApps: 12,
    confTitles: 8,
    recentRankings: [{ yr: 2025, rk: 35 }, { yr: 2024, rk: 38 }, { yr: 2023, rk: 32 }],
    headCoach: "Chris Hamblin",
    coachTenure: "2014–present (12th season)",
    coachRecord: "105-55-20 (.639)",
    coachPhilosophy: "Smart, tactical play leveraging high-IQ athletes, structured defense",
    coachHighlights: ["Multiple Ivy League titles", "Consistent conference contender", "Recruits top scholar-athletes"],
    famousAlumni: [
      { name: "Margaret 'Midge' Purce", note: "USWNT, NJ/NY Gotham FC, NWSL star" },
      { name: "Lara Brait", note: "Professional goalkeeper" }
    ],
    keyPlayers: ["Murphy Agnew (F)", "Ainsley Ahmadian (M)", "Lara Brait (GK)"],
    playStyle: "Intelligent, structured, tactical. High soccer IQ matches high academic IQ.",
    reputation: "Best academic profile in the country. No athletic scholarships (Ivy League) — attracts true scholar-athletes.",
    rivalries: ["Yale (The Game, all sports)", "Princeton (Ivy)"],
    academicRank: 1,
    notablePrograms: ["Everything — Business, Law, Medicine, Government, STEM, Humanities"],
    gradRate: 99,
    athleteSupport: "Bureau of Study Counsel, academic advising, unmatched network",
    scholarships: 0,
    facilityQuality: "Good",
    facilities: "Jordan Field (3,000 cap), Dillon Field House, Murr Center",
    climate: "Continental — cold snowy winters, warm humid summers, gorgeous fall",
    campusVibe: "Historic, intellectual, prestigious — the world's most famous university campus",
    surroundingArea: "Cambridge/Boston — world-class city, culture, history, restaurants, MIT next door",
    fitScores: { athletic: 68, academic: 100, location: 88, resources: 72 }
  },
  {
    id: "brown",
    name: "Brown University",
    nickname: "Bears",
    conference: "Ivy League",
    city: "Providence", state: "RI", region: "Northeast",
    colors: ["#4E3629", "#C00404"],
    historicalRecord: { wins: 280, losses: 155, draws: 50, winPct: .630 },
    nationalTitles: 0,
    titleYears: "—",
    ncaaTourneyApps: 10,
    confTitles: 5,
    recentRankings: [{ yr: 2025, rk: 30 }, { yr: 2024, rk: 34 }, { yr: 2023, rk: 30 }],
    headCoach: "Kia McNeill",
    coachTenure: "2013–present (13th season)",
    coachRecord: "115-65-25 (.622)",
    coachPhilosophy: "Player development, creative expression, building confident athletes",
    coachHighlights: ["Consistent Ivy League contender", "5 Ivy titles", "Strong 2025 season (9-2-4)"],
    famousAlumni: [
      { name: "Vanessa DiBernardo", note: "NWSL veteran midfielder" },
      { name: "Erin Baxter", note: "Professional soccer" }
    ],
    keyPlayers: ["Ava Seelenfreund (F)", "Esha Mam (M)", "Isabelle Washington (D)"],
    playStyle: "Creative, expressive — mirrors Brown's open curriculum philosophy. Skilled, thoughtful play.",
    reputation: "Strong Ivy program with growing ambitions. Open curriculum = flexible athlete schedule.",
    rivalries: ["Princeton (Ivy title race)", "Yale (Ivy)"],
    academicRank: 9,
    notablePrograms: ["Open Curriculum (design your own)", "Computer Science", "International Relations", "Applied Math"],
    gradRate: 98,
    athleteSupport: "Academic advising, flexible scheduling, tight faculty relationships",
    scholarships: 0,
    facilityQuality: "Good",
    facilities: "Stevenson-Pincince Field (3,000 cap), Nelson Fitness Center, training fields",
    climate: "Continental — cold winters, warm humid summers, beautiful New England fall",
    campusVibe: "Progressive, creative, intellectual freedom — open curriculum, diverse community",
    surroundingArea: "Providence — arts scene (RISD next door), food culture, 1 hr to Boston",
    fitScores: { athletic: 66, academic: 96, location: 82, resources: 68 }
  },
  {
    id: "princeton",
    name: "Princeton University",
    nickname: "Tigers",
    conference: "Ivy League",
    city: "Princeton", state: "NJ", region: "Northeast",
    colors: ["#FF6600", "#000000"],
    historicalRecord: { wins: 330, losses: 120, draws: 40, winPct: .714 },
    nationalTitles: 0,
    titleYears: "—",
    ncaaTourneyApps: 14,
    confTitles: 10,
    recentRankings: [{ yr: 2025, rk: 25 }, { yr: 2024, rk: 28 }, { yr: 2023, rk: 26 }],
    headCoach: "Sean Driscoll",
    coachTenure: "2020–present (6th season)",
    coachRecord: "55-15-8 (.756)",
    coachPhilosophy: "Technical excellence, high-pressing, competitive edge within an academic framework",
    coachHighlights: ["10 Ivy League titles (program history)", "Picked #1 in 2025 Ivy preseason poll", "Strong winning percentage"],
    famousAlumni: [
      { name: "Tyler Lussi", note: "NWSL, Portland Thorns" },
      { name: "Mimi Asom", note: "NWSL professional" }
    ],
    keyPlayers: ["Erin Sheehan (F)", "Lauren Cornachio (M)", "Ellie Sands (D)"],
    playStyle: "Sharp, tactical, high-pressing Ivy style. Technically proficient with competitive fire.",
    reputation: "Best Ivy League team — 10 conference titles, picked #1 in 2025. Elite academics + strong soccer.",
    rivalries: ["Harvard (Ivy)", "Brown (Ivy title contenders)"],
    academicRank: 1,
    notablePrograms: ["Public Policy (Woodrow Wilson)", "Engineering", "Economics", "Mathematics"],
    gradRate: 99,
    athleteSupport: "Academic advisors, flexible class scheduling, world-class facilities for Ivy",
    scholarships: 0,
    facilityQuality: "Excellent",
    facilities: "Roberts Stadium (5,000 cap), Caldwell Fieldhouse, Dillon Gymnasium",
    climate: "Continental — cold winters, warm humid summers, classic Northeast seasons",
    campusVibe: "Gorgeous Gothic campus, intimate intellectual community, strong athletic tradition for Ivy",
    surroundingArea: "Princeton — charming college town, 1 hr to NYC and Philly, NJ Transit access",
    fitScores: { athletic: 72, academic: 100, location: 85, resources: 75 }
  }
];

// ─── CONSTANTS ───────────────────────────────────────────────────────────────
const CONFERENCES = [...new Set(SCHOOLS.map(s => s.conference))].sort();
const REGIONS = [...new Set(SCHOOLS.map(s => s.region))].sort();

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "history", label: "History & Records" },
  { key: "coaching", label: "Coaching" },
  { key: "alumni", label: "Famous Alumni" },
  { key: "roster", label: "Current Players" },
  { key: "traditions", label: "Traditions" },
  { key: "academics", label: "Academics" },
  { key: "resources", label: "Funding" },
  { key: "location", label: "Location" },
];

// ─── UTILITY ─────────────────────────────────────────────────────────────────
const avg = (s, key) => Math.round((s.fitScores.athletic + s.fitScores.academic + s.fitScores.location + s.fitScores.resources) / 4);
const pct = v => `${v}%`;

// ─── BADGE / TAG COMPONENTS ──────────────────────────────────────────────────
function Badge({ children, color = "#6366f1" }) {
  return <span style={{ background: color + "22", color, padding: "2px 10px", borderRadius: 9999, fontSize: 12, fontWeight: 600, whiteSpace: "nowrap" }}>{children}</span>;
}
function Tag({ children }) {
  return <span style={{ background: "#f1f5f9", color: "#475569", padding: "2px 8px", borderRadius: 6, fontSize: 11, fontWeight: 500 }}>{children}</span>;
}
function StatBox({ label, value, sub }) {
  return (
    <div style={{ textAlign: "center", padding: "10px 14px", background: "#f8fafc", borderRadius: 10, minWidth: 90 }}>
      <div style={{ fontSize: 22, fontWeight: 700, color: "#1e293b" }}>{value}</div>
      <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>{label}</div>
      {sub && <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 1 }}>{sub}</div>}
    </div>
  );
}
function ProgressBar({ value, max = 100, color = "#6366f1" }) {
  return (
    <div style={{ background: "#e2e8f0", borderRadius: 6, height: 8, width: "100%", overflow: "hidden" }}>
      <div style={{ width: pct(Math.min(value, max)), background: color, height: "100%", borderRadius: 6, transition: "width 0.4s ease" }} />
    </div>
  );
}

// ─── DETAIL TAB CONTENT ──────────────────────────────────────────────────────
function TabOverview({ s }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <div>
        <h4 style={{ margin: "0 0 8px", fontSize: 14, color: "#64748b" }}>Program Snapshot</h4>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
          <StatBox label="Nat'l Titles" value={s.nationalTitles} />
          <StatBox label="NCAA Tourneys" value={s.ncaaTourneyApps} />
          <StatBox label="Conf. Titles" value={s.confTitles} />
        </div>
        <p style={{ fontSize: 13, color: "#475569", lineHeight: 1.6, margin: 0 }}>{s.reputation}</p>
      </div>
      <div>
        <h4 style={{ margin: "0 0 8px", fontSize: 14, color: "#64748b" }}>Fit Scores</h4>
        {Object.entries(s.fitScores).map(([k, v]) => (
          <div key={k} style={{ marginBottom: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 3 }}>
              <span style={{ textTransform: "capitalize", color: "#334155" }}>{k}</span>
              <span style={{ fontWeight: 600, color: "#1e293b" }}>{v}</span>
            </div>
            <ProgressBar value={v} color={v >= 90 ? "#22c55e" : v >= 75 ? "#6366f1" : "#f59e0b"} />
          </div>
        ))}
        <div style={{ marginTop: 10, padding: "8px 12px", background: "#f0fdf4", borderRadius: 8, textAlign: "center" }}>
          <span style={{ fontSize: 12, color: "#15803d" }}>Overall Fit: </span>
          <span style={{ fontSize: 18, fontWeight: 700, color: "#15803d" }}>{avg(s)}</span>
        </div>
      </div>
    </div>
  );
}

function TabHistory({ s }) {
  return (
    <div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
        <StatBox label="Wins" value={s.historicalRecord.wins} />
        <StatBox label="Losses" value={s.historicalRecord.losses} />
        <StatBox label="Draws" value={s.historicalRecord.draws} />
        <StatBox label="Win %" value={pct(Math.round(s.historicalRecord.winPct * 100))} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div>
          <h4 style={{ margin: "0 0 6px", fontSize: 14, color: "#64748b" }}>Championships</h4>
          <p style={{ fontSize: 13, color: "#1e293b", margin: "0 0 4px" }}><strong>{s.nationalTitles}</strong> National Title{s.nationalTitles !== 1 ? "s" : ""}</p>
          {s.titleYears !== "—" && <p style={{ fontSize: 12, color: "#64748b", margin: 0 }}>{s.titleYears}</p>}
          <p style={{ fontSize: 13, color: "#1e293b", margin: "8px 0 0" }}><strong>{s.confTitles}</strong> Conference Title{s.confTitles !== 1 ? "s" : ""}</p>
        </div>
        <div>
          <h4 style={{ margin: "0 0 6px", fontSize: 14, color: "#64748b" }}>Recent Rankings</h4>
          {s.recentRankings.map(r => (
            <div key={r.yr} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "3px 0", borderBottom: "1px solid #f1f5f9" }}>
              <span style={{ color: "#64748b" }}>{r.yr}</span>
              <span style={{ fontWeight: 600, color: "#1e293b" }}>#{r.rk}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function TabCoaching({ s }) {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <div style={{ width: 48, height: 48, borderRadius: "50%", background: s.colors[0], display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: 700, fontSize: 18 }}>
          {s.headCoach.split(" ").map(n => n[0]).join("")}
        </div>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: "#1e293b" }}>{s.headCoach}</div>
          <div style={{ fontSize: 12, color: "#64748b" }}>{s.coachTenure}</div>
        </div>
      </div>
      <p style={{ fontSize: 13, color: "#475569", margin: "0 0 8px" }}><strong>Record:</strong> {s.coachRecord}</p>
      <p style={{ fontSize: 13, color: "#475569", margin: "0 0 12px" }}><strong>Philosophy:</strong> {s.coachPhilosophy}</p>
      <h4 style={{ margin: "0 0 6px", fontSize: 14, color: "#64748b" }}>Highlights</h4>
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        {s.coachHighlights.map((h, i) => <li key={i} style={{ fontSize: 13, color: "#334155", marginBottom: 4 }}>{h}</li>)}
      </ul>
    </div>
  );
}

function TabAlumni({ s }) {
  return (
    <div>
      <h4 style={{ margin: "0 0 10px", fontSize: 14, color: "#64748b" }}>Notable Alumni</h4>
      {s.famousAlumni.map((a, i) => (
        <div key={i} style={{ display: "flex", gap: 10, padding: "8px 0", borderBottom: i < s.famousAlumni.length - 1 ? "1px solid #f1f5f9" : "none" }}>
          <div style={{ width: 36, height: 36, borderRadius: "50%", background: "#e0e7ff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 600, color: "#6366f1", flexShrink: 0 }}>
            {a.name.split(" ").map(n => n[0]).join("")}
          </div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: "#1e293b" }}>{a.name}</div>
            <div style={{ fontSize: 12, color: "#64748b" }}>{a.note}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function TabRoster({ s }) {
  return (
    <div>
      <h4 style={{ margin: "0 0 10px", fontSize: 14, color: "#64748b" }}>Key Players (2024-25)</h4>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {s.keyPlayers.map((p, i) => (
          <div key={i} style={{ background: "#f8fafc", padding: "8px 14px", borderRadius: 8, fontSize: 13, color: "#1e293b", border: "1px solid #e2e8f0" }}>
            {p}
          </div>
        ))}
      </div>
      <p style={{ fontSize: 12, color: "#94a3b8", marginTop: 12 }}>Full roster available on {s.nickname} athletics website</p>
    </div>
  );
}

function TabTraditions({ s }) {
  return (
    <div>
      <div style={{ marginBottom: 14 }}>
        <h4 style={{ margin: "0 0 4px", fontSize: 14, color: "#64748b" }}>Play Style</h4>
        <p style={{ fontSize: 13, color: "#1e293b", margin: 0, lineHeight: 1.6 }}>{s.playStyle}</p>
      </div>
      <div style={{ marginBottom: 14 }}>
        <h4 style={{ margin: "0 0 4px", fontSize: 14, color: "#64748b" }}>Reputation</h4>
        <p style={{ fontSize: 13, color: "#1e293b", margin: 0, lineHeight: 1.6 }}>{s.reputation}</p>
      </div>
      <div>
        <h4 style={{ margin: "0 0 6px", fontSize: 14, color: "#64748b" }}>Key Rivalries</h4>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {s.rivalries.map((r, i) => <Tag key={i}>{r}</Tag>)}
        </div>
      </div>
    </div>
  );
}

function TabAcademics({ s }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <div>
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <StatBox label="US News Rank" value={`#${s.academicRank}`} />
          <StatBox label="Grad Rate" value={pct(s.gradRate)} />
        </div>
        <h4 style={{ margin: "0 0 6px", fontSize: 14, color: "#64748b" }}>Notable Programs</h4>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {s.notablePrograms.map((p, i) => <Tag key={i}>{p}</Tag>)}
        </div>
      </div>
      <div>
        <h4 style={{ margin: "0 0 6px", fontSize: 14, color: "#64748b" }}>Athlete Support</h4>
        <p style={{ fontSize: 13, color: "#475569", margin: "0 0 10px", lineHeight: 1.6 }}>{s.athleteSupport}</p>
        <h4 style={{ margin: "0 0 6px", fontSize: 14, color: "#64748b" }}>Scholarships</h4>
        <p style={{ fontSize: 13, color: "#1e293b", margin: 0 }}>
          {s.scholarships > 0 ? `${s.scholarships} full athletic scholarships` : "No athletic scholarships (Ivy League — need-based aid only)"}
        </p>
      </div>
    </div>
  );
}

function TabResources({ s }) {
  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
        <StatBox label="Scholarships" value={s.scholarships} sub={s.scholarships > 0 ? "full rides" : "need-based"} />
        <StatBox label="Facility Grade" value={s.facilityQuality} />
      </div>
      <h4 style={{ margin: "0 0 6px", fontSize: 14, color: "#64748b" }}>Facilities</h4>
      <p style={{ fontSize: 13, color: "#475569", margin: 0, lineHeight: 1.6 }}>{s.facilities}</p>
    </div>
  );
}

function TabLocation({ s }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <div>
        <h4 style={{ margin: "0 0 6px", fontSize: 14, color: "#64748b" }}>Climate</h4>
        <p style={{ fontSize: 13, color: "#475569", margin: "0 0 14px", lineHeight: 1.6 }}>{s.climate}</p>
        <h4 style={{ margin: "0 0 6px", fontSize: 14, color: "#64748b" }}>Campus Vibe</h4>
        <p style={{ fontSize: 13, color: "#475569", margin: 0, lineHeight: 1.6 }}>{s.campusVibe}</p>
      </div>
      <div>
        <h4 style={{ margin: "0 0 6px", fontSize: 14, color: "#64748b" }}>Surrounding Area</h4>
        <p style={{ fontSize: 13, color: "#475569", margin: 0, lineHeight: 1.6 }}>{s.surroundingArea}</p>
      </div>
    </div>
  );
}

const TAB_COMPONENTS = {
  overview: TabOverview, history: TabHistory, coaching: TabCoaching,
  alumni: TabAlumni, roster: TabRoster, traditions: TabTraditions,
  academics: TabAcademics, resources: TabResources, location: TabLocation,
};

// ─── SCHOOL CARD ─────────────────────────────────────────────────────────────
function SchoolCard({ s, expanded, onToggle, compareMode, isCompared, onCompare }) {
  const [activeTab, setActiveTab] = useState("overview");
  const TabContent = TAB_COMPONENTS[activeTab];
  const overallFit = avg(s);
  return (
    <div style={{
      background: "#fff", borderRadius: 14, border: isCompared ? "2px solid #6366f1" : "1px solid #e2e8f0",
      overflow: "hidden", transition: "all 0.25s ease", boxShadow: expanded ? "0 8px 30px rgba(0,0,0,0.08)" : "0 1px 3px rgba(0,0,0,0.04)"
    }}>
      {/* Header bar with school color */}
      <div style={{ height: 4, background: `linear-gradient(90deg, ${s.colors[0]}, ${s.colors[1] || s.colors[0]}88)` }} />
      <div style={{ padding: "14px 18px", cursor: "pointer" }} onClick={onToggle}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div style={{ flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <span style={{ fontSize: 17, fontWeight: 700, color: "#1e293b" }}>{s.name}</span>
              {s.nationalTitles > 0 && <Badge color="#eab308">{s.nationalTitles} Title{s.nationalTitles > 1 ? "s" : ""}</Badge>}
            </div>
            <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
              <Tag>{s.nickname}</Tag>
              <Tag>{s.conference}</Tag>
              <Tag>{s.city}, {s.state}</Tag>
              {s.recentRankings[0] && <Badge color="#6366f1">#{s.recentRankings[0].rk} ({s.recentRankings[0].yr})</Badge>}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {compareMode && (
              <button onClick={e => { e.stopPropagation(); onCompare(s.id); }}
                style={{ padding: "4px 12px", borderRadius: 8, border: isCompared ? "2px solid #6366f1" : "1px solid #cbd5e1",
                  background: isCompared ? "#eef2ff" : "#fff", color: isCompared ? "#6366f1" : "#64748b",
                  fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                {isCompared ? "Selected" : "Compare"}
              </button>
            )}
            <div style={{ background: overallFit >= 85 ? "#dcfce7" : overallFit >= 70 ? "#e0e7ff" : "#fef3c7",
              borderRadius: 10, padding: "6px 12px", textAlign: "center", minWidth: 50 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: overallFit >= 85 ? "#15803d" : overallFit >= 70 ? "#4338ca" : "#b45309" }}>{overallFit}</div>
              <div style={{ fontSize: 9, color: "#64748b" }}>FIT</div>
            </div>
            <span style={{ fontSize: 18, color: "#94a3b8", transition: "transform 0.2s", transform: expanded ? "rotate(180deg)" : "rotate(0)" }}>&#9660;</span>
          </div>
        </div>
      </div>
      {/* Expanded detail */}
      {expanded && (
        <div style={{ borderTop: "1px solid #f1f5f9", padding: "0 18px 18px" }}>
          {/* Tabs */}
          <div style={{ display: "flex", gap: 2, overflowX: "auto", padding: "12px 0 14px", borderBottom: "1px solid #f1f5f9", marginBottom: 14 }}>
            {TABS.map(t => (
              <button key={t.key} onClick={() => setActiveTab(t.key)}
                style={{ padding: "5px 12px", borderRadius: 8, border: "none",
                  background: activeTab === t.key ? s.colors[0] : "transparent",
                  color: activeTab === t.key ? "#fff" : "#64748b",
                  fontSize: 12, fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap", transition: "all 0.15s" }}>
                {t.label}
              </button>
            ))}
          </div>
          <TabContent s={s} />
        </div>
      )}
    </div>
  );
}

// ─── COMPARISON VIEW ─────────────────────────────────────────────────────────
function ComparisonView({ schools }) {
  if (schools.length < 2) return <div style={{ textAlign: "center", padding: 40, color: "#94a3b8" }}>Select at least 2 schools to compare</div>;

  const radarData = [
    { metric: "Athletic", ...Object.fromEntries(schools.map(s => [s.id, s.fitScores.athletic])) },
    { metric: "Academic", ...Object.fromEntries(schools.map(s => [s.id, s.fitScores.academic])) },
    { metric: "Location", ...Object.fromEntries(schools.map(s => [s.id, s.fitScores.location])) },
    { metric: "Resources", ...Object.fromEntries(schools.map(s => [s.id, s.fitScores.resources])) },
  ];

  const colors = ["#6366f1", "#ec4899", "#f59e0b", "#22c55e"];
  const barData = schools.map(s => ({ name: s.nickname, titles: s.nationalTitles, tourneys: s.ncaaTourneyApps, confTitles: s.confTitles }));
  const rankData = schools[0].recentRankings.map((_, i) => {
    const obj = { year: schools[0].recentRankings[i].yr };
    schools.forEach(s => { if (s.recentRankings[i]) obj[s.id] = s.recentRankings[i].rk; });
    return obj;
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Charts row */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div style={{ background: "#fff", borderRadius: 14, padding: 18, border: "1px solid #e2e8f0" }}>
          <h3 style={{ margin: "0 0 10px", fontSize: 15, color: "#1e293b" }}>Fit Score Comparison</h3>
          <ResponsiveContainer width="100%" height={260}>
            <RadarChart data={radarData}>
              <PolarGrid stroke="#e2e8f0" />
              <PolarAngleAxis dataKey="metric" tick={{ fontSize: 12, fill: "#64748b" }} />
              <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fontSize: 10 }} />
              {schools.map((s, i) => <Radar key={s.id} name={s.nickname} dataKey={s.id} stroke={colors[i]} fill={colors[i]} fillOpacity={0.15} />)}
              <Legend wrapperStyle={{ fontSize: 12 }} />
            </RadarChart>
          </ResponsiveContainer>
        </div>
        <div style={{ background: "#fff", borderRadius: 14, padding: 18, border: "1px solid #e2e8f0" }}>
          <h3 style={{ margin: "0 0 10px", fontSize: 15, color: "#1e293b" }}>Titles & Tournament Appearances</h3>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={barData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip contentStyle={{ fontSize: 12 }} />
              <Bar dataKey="titles" fill="#6366f1" name="National Titles" radius={[4, 4, 0, 0]} />
              <Bar dataKey="tourneys" fill="#a5b4fc" name="NCAA Tourneys" radius={[4, 4, 0, 0]} />
              <Bar dataKey="confTitles" fill="#c4b5fd" name="Conf Titles" radius={[4, 4, 0, 0]} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      {/* Ranking trend */}
      <div style={{ background: "#fff", borderRadius: 14, padding: 18, border: "1px solid #e2e8f0" }}>
        <h3 style={{ margin: "0 0 10px", fontSize: 15, color: "#1e293b" }}>Ranking Trend (Lower = Better)</h3>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={rankData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis dataKey="year" tick={{ fontSize: 11 }} />
            <YAxis reversed domain={[1, "dataMax + 5"]} tick={{ fontSize: 11 }} />
            <Tooltip contentStyle={{ fontSize: 12 }} />
            {schools.map((s, i) => <Line key={s.id} type="monotone" dataKey={s.id} stroke={colors[i]} name={s.nickname} strokeWidth={2} dot={{ r: 4 }} />)}
            <Legend wrapperStyle={{ fontSize: 12 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {/* Side-by-side details */}
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${schools.length}, 1fr)`, gap: 12 }}>
        {schools.map(s => (
          <div key={s.id} style={{ background: "#fff", borderRadius: 14, padding: 16, border: "1px solid #e2e8f0" }}>
            <div style={{ height: 4, background: s.colors[0], borderRadius: 4, marginBottom: 12 }} />
            <h3 style={{ margin: "0 0 6px", fontSize: 15, color: "#1e293b" }}>{s.nickname}</h3>
            <p style={{ fontSize: 12, color: "#64748b", margin: "0 0 10px" }}>{s.conference} | {s.city}, {s.state}</p>
            <div style={{ fontSize: 12, color: "#334155", lineHeight: 1.8 }}>
              <div><strong>Coach:</strong> {s.headCoach}</div>
              <div><strong>Record:</strong> {s.historicalRecord.wins}-{s.historicalRecord.losses}-{s.historicalRecord.draws}</div>
              <div><strong>Titles:</strong> {s.nationalTitles}</div>
              <div><strong>Academic Rank:</strong> #{s.academicRank}</div>
              <div><strong>Grad Rate:</strong> {s.gradRate}%</div>
              <div><strong>Scholarships:</strong> {s.scholarships > 0 ? s.scholarships : "Need-based"}</div>
              <div><strong>Style:</strong> {s.playStyle.slice(0, 80)}...</div>
              <div><strong>Climate:</strong> {s.climate.split("—")[0]}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── MAIN APP ────────────────────────────────────────────────────────────────
export default function CollegeSoccerDashboard() {
  const [search, setSearch] = useState("");
  const [confFilter, setConfFilter] = useState("All");
  const [regionFilter, setRegionFilter] = useState("All");
  const [sortBy, setSortBy] = useState("ranking");
  const [expandedId, setExpandedId] = useState(null);
  const [compareMode, setCompareMode] = useState(false);
  const [compareIds, setCompareIds] = useState([]);
  const [view, setView] = useState("grid"); // grid | compare

  const toggleCompare = useCallback((id) => {
    setCompareIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : prev.length < 4 ? [...prev, id] : prev);
  }, []);

  const filtered = useMemo(() => {
    let list = SCHOOLS.filter(s => {
      if (search && !`${s.name} ${s.nickname} ${s.city} ${s.conference}`.toLowerCase().includes(search.toLowerCase())) return false;
      if (confFilter !== "All" && s.conference !== confFilter) return false;
      if (regionFilter !== "All" && s.region !== regionFilter) return false;
      return true;
    });
    if (sortBy === "ranking") list.sort((a, b) => (a.recentRankings[0]?.rk || 99) - (b.recentRankings[0]?.rk || 99));
    else if (sortBy === "academic") list.sort((a, b) => a.academicRank - b.academicRank);
    else if (sortBy === "titles") list.sort((a, b) => b.nationalTitles - a.nationalTitles);
    else if (sortBy === "fit") list.sort((a, b) => avg(b) - avg(a));
    else if (sortBy === "name") list.sort((a, b) => a.name.localeCompare(b.name));
    return list;
  }, [search, confFilter, regionFilter, sortBy]);

  const comparedSchools = SCHOOLS.filter(s => compareIds.includes(s.id));

  return (
    <div style={{ fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", background: "#f8fafc", minHeight: "100vh" }}>
      {/* Header */}
      <div style={{ background: "linear-gradient(135deg, #1e293b 0%, #334155 100%)", padding: "24px 28px 20px", color: "#fff" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 800 }}>D1 Women's Soccer Dashboard</h1>
            <p style={{ margin: "4px 0 0", fontSize: 13, color: "#94a3b8" }}>Recruiting Research — {SCHOOLS.length} Programs</p>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={() => { setView("grid"); setCompareMode(false); }}
              style={{ padding: "7px 16px", borderRadius: 8, border: "none", background: view === "grid" ? "#6366f1" : "#475569", color: "#fff", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
              Browse
            </button>
            <button onClick={() => { setView("compare"); setCompareMode(true); }}
              style={{ padding: "7px 16px", borderRadius: 8, border: "none", background: view === "compare" ? "#6366f1" : "#475569", color: "#fff", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
              Compare {compareIds.length > 0 && `(${compareIds.length})`}
            </button>
          </div>
        </div>
        {/* Filters */}
        <div style={{ display: "flex", gap: 10, marginTop: 16, flexWrap: "wrap", alignItems: "center" }}>
          <input type="text" placeholder="Search schools, cities, conferences..." value={search} onChange={e => setSearch(e.target.value)}
            style={{ padding: "8px 14px", borderRadius: 8, border: "1px solid #475569", background: "#1e293b", color: "#fff", fontSize: 13, width: 260, outline: "none" }} />
          <select value={confFilter} onChange={e => setConfFilter(e.target.value)}
            style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #475569", background: "#1e293b", color: "#fff", fontSize: 13, cursor: "pointer" }}>
            <option value="All">All Conferences</option>
            {CONFERENCES.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <select value={regionFilter} onChange={e => setRegionFilter(e.target.value)}
            style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #475569", background: "#1e293b", color: "#fff", fontSize: 13, cursor: "pointer" }}>
            <option value="All">All Regions</option>
            {REGIONS.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
          <select value={sortBy} onChange={e => setSortBy(e.target.value)}
            style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #475569", background: "#1e293b", color: "#fff", fontSize: 13, cursor: "pointer" }}>
            <option value="ranking">Sort: Ranking</option>
            <option value="academic">Sort: Academic Rank</option>
            <option value="titles">Sort: National Titles</option>
            <option value="fit">Sort: Fit Score</option>
            <option value="name">Sort: Name</option>
          </select>
          {compareMode && compareIds.length > 0 && (
            <button onClick={() => setCompareIds([])}
              style={{ padding: "8px 14px", borderRadius: 8, border: "1px solid #f87171", background: "transparent", color: "#f87171", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
              Clear Selection
            </button>
          )}
        </div>
      </div>

      {/* Content */}
      <div style={{ padding: "20px 28px", maxWidth: 1200, margin: "0 auto" }}>
        {view === "compare" ? (
          <ComparisonView schools={comparedSchools} />
        ) : (
          <>
            <div style={{ fontSize: 13, color: "#64748b", marginBottom: 14 }}>{filtered.length} school{filtered.length !== 1 ? "s" : ""} found</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {filtered.map(s => (
                <SchoolCard key={s.id} s={s} expanded={expandedId === s.id}
                  onToggle={() => setExpandedId(expandedId === s.id ? null : s.id)}
                  compareMode={compareMode} isCompared={compareIds.includes(s.id)}
                  onCompare={toggleCompare} />
              ))}
            </div>
          </>
        )}
      </div>

      {/* Footer */}
      <div style={{ textAlign: "center", padding: "24px 28px", color: "#94a3b8", fontSize: 11, borderTop: "1px solid #e2e8f0", marginTop: 20 }}>
        D1 Women's Soccer Recruiting Dashboard | Data compiled from NCAA, United Soccer Coaches, school athletic sites | Last updated March 2026
      </div>
    </div>
  );
}
