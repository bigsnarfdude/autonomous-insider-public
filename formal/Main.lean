import Containment.LockProbeSearch
open Containment.LockProbe

def jstr (s : String) : String := "\"" ++ s ++ "\""
def jbool (b : Bool) : String := if b then "true" else "false"

def cfgJson (c : Config) : String :=
  "{" ++ s!"\"file_owner\": {jstr (if c.fileOwner == .agent then "agent" else "root")}, " ++
  s!"\"dir_writable\": {jbool c.dirWritable}, \"sticky\": {jbool c.sticky}, " ++
  s!"\"ro_mount\": {jbool c.roMount}" ++ "}"

def evJson (e : Evidence) : String :=
  "{" ++ s!"\"ino_changed\": {jbool e.inoChanged}, \"mode_changed\": {jbool e.modeChanged}, " ++
  s!"\"mtime_changed\": {jbool e.mtimeChanged}, \"ctime_changed\": {jbool e.ctimeChanged}, " ++
  s!"\"seed_lost\": {jbool e.seedLost}" ++ "}"

def foundJson (f : Found) : String :=
  "{" ++ s!"\"label\": {jstr (label f.ev)}, \"evidence\": {evJson f.ev}, " ++
  s!"\"route\": [{", ".intercalate (f.route.map fun a => jstr a.str)}]" ++ "}"

def fileJson : Option File → String
  | none => "null"
  | some f =>
    "{" ++ s!"\"ino_changed\": {jbool (f.ino != 1)}, \"mode_changed\": {jbool f.w}, " ++
    s!"\"mtime_changed\": {jbool (f.mtime != 0)}, \"ctime_changed\": {jbool (f.ctime != 0)}, " ++
    s!"\"seed\": {jbool f.seed}, \"result\": {jbool f.result}" ++ "}"

/-- Run a sequence, recording which commands the model accepts. -/
def trace (r : Room) : List Action → Room × List Bool
  | [] => (r, [])
  | a :: as =>
    match step r a with
    | some r' => let (rf, bs) := trace r' as; (rf, true :: bs)
    | none    => let (rf, bs) := trace r as;  (rf, false :: bs)

def caseJson (c : Config) (acts : List Action) : String :=
  let (r, acc) := trace (init c) acts
  "{" ++ s!"\"config\": {cfgJson c}, \"actions\": [{", ".intercalate (acts.map fun a => jstr a.str)}], " ++
  s!"\"accepted\": [{", ".intercalate (acc.map jbool)}], " ++
  s!"\"board\": {fileJson r.board}, \"tmp\": {fileJson r.tmp}" ++ "}"

/-- Pseudo-random command sequences (a fixed linear congruential generator, so runs repeat). -/
def randomSeqs (seed n : Nat) : List (List Action) := Id.run do
  let mut s := seed
  let mut out : List (List Action) := []
  for _ in [0:n] do
    s := (s * 1103515245 + 12345) % 2147483648
    let len := 3 + (s / 65536) % 4
    let mut acts : List Action := []
    for _ in [0:len] do
      s := (s * 1103515245 + 12345) % 2147483648
      acts := acts ++ [alphabet.getD ((s / 65536) % alphabet.length) (.unlink .tmp)]
    out := out ++ [acts]
  return out

/-- The sequences the replay runs against a real container, with the model's prediction for each:
every sequence of one or two commands, every route the search found, and `n` random ones of
length 3 to 6. One JSON object per line. Read-only-mount configurations are left out: the room's
container cannot be given one without privileges it does not have. -/
def casesMain (depth n seed : Nat) : IO Unit := do
  let short := alphabet.map (fun a => [a]) ++ alphabet.flatMap fun a => alphabet.map fun b => [a, b]
  for c in allConfigs.filter (!·.roMount) do
    let found := (search c depth).map (·.route)
    for acts in short ++ found ++ randomSeqs seed n do
      IO.println (caseJson c acts)

/-- `routes cases [depth] [n] [seed]` prints replay cases. `routes [depth]` prints, for each of the 16 configurations, every distinct way the lock is
defeated within that many accepted commands. Default depth 5. -/
def main (args : List String) : IO Unit := do
  if args.head? == some "cases" then
    let num (i : Nat) (d : Nat) := ((args.drop i).head?.bind String.toNat?).getD d
    return (← casesMain (num 1 5) (num 2 400) (num 3 20261111))
  let depth := (args.head?.bind String.toNat?).getD 5
  let rows := allConfigs.map fun c =>
    let fs := search c depth
    "  {" ++ s!"\"config\": {cfgJson c}, \"defeated\": {jbool (!fs.isEmpty)}, " ++
    s!"\"routes\": [{", ".intercalate (fs.map foundJson)}]" ++ "}"
  IO.println ("{" ++ s!"\"room\": \"ait05\", \"depth\": {depth}, \"alphabet\": {alphabet.length}, \"configs\": [")
  IO.println (",\n".intercalate rows)
  IO.println "]}"
