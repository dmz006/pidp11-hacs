# Diagrams

All diagrams are Mermaid; GitHub, most IDEs, and `mdbook-mermaid` render
them inline.

---

## 1. System context

```mermaid
graph LR
    user([User])
    phone([HA mobile app])
    ha[[Home Assistant<br/>Core]]
    sup[[Supervisor]]
    addon[[pidp11-addon<br/>container]]
    simh[(SimH<br/>PDP-11)]
    panel{{PiDP-11<br/>hat}}
    gpio[/Pi 5 RP1<br/>/dev/mem/]

    user -- "SSH :2211" --> addon
    user -- "Lovelace UI" --> ha
    phone -- HTTPS --> ha
    ha -- "loads HACS<br/>custom_components/pidp11" --> ha
    ha -- "TCP :2223<br/>remote console" --> addon
    sup -- "runs / restarts" --> addon
    addon --> simh
    simh -- "mmap" --> gpio
    gpio <--> panel
```

## 2. Component (inside the add-on container)

```mermaid
graph TB
    subgraph Container["pidp11-addon container (privileged: SYS_RAWIO)"]
        run[run.sh<br/>entrypoint]
        s6[s6-overlay<br/>supervisor]
        db[dropbear<br/>:22]
        scr[GNU screen<br/>session 'pidp11']
        simh[SimH pdp11<br/>+ pidp11 GPIO driver]
        rc[SimH remote console<br/>listener :2223]
        sel[boot-selector<br/>service]
        opts[/data/options.json/]
        disks[(/share/pidp11/disks/)]
    end

    run --> s6
    s6 --> db
    s6 --> simh
    s6 --> sel
    db --> scr
    scr --> simh
    simh --> rc
    sel --> simh
    opts --> sel
    simh <--> disks
```

## 3. Deployment (single Pi 5 node)

```mermaid
graph TB
    subgraph Pi5["Raspberry Pi 5 + PiDP-11 hat"]
        subgraph HAOS["HAOS (host)"]
            subgraph Sup["Supervisor"]
                ha[[homeassistant<br/>container]]
                addon2[[pidp11-addon<br/>container]]
            end
            share[(/mnt/data/supervisor/share)]
            devmem[/dev/mem/]
        end
        hat{{PiDP-11 hat<br/>40-pin header}}
    end

    ha -- "TCP :2223" --> addon2
    addon2 -- "SSH :22 -> host :2211" --> addon2
    addon2 -. "bind-mount" .-> share
    addon2 -. "device" .-> devmem
    devmem <--> hat
```

## 4. Sequence — user SSH console

```mermaid
sequenceDiagram
    actor U as User
    participant D as dropbear :2211
    participant W as login-wrapper
    participant S as screen -RR pidp11
    participant E as SimH pdp11

    U->>D: ssh pidp11@haos:2211
    D->>U: password prompt
    U-->>D: password
    D->>W: exec wrapper as pdp11-user
    W->>S: attach / create session
    alt session exists
        S->>U: replay last screen
    else fresh boot
        S->>E: spawn /opt/pidp11/bin/pdp11<br/>with default boot
        E-->>S: ". (prompt)"
        S-->>U: ". (prompt)"
    end
    U->>E: running programs...
    U->>S: ^A d  (detach)
    S-->>U: "[detached]"
    U->>D: exit
    Note over E: Emulator keeps running<br/>on front panel
```

## 5. Sequence — HA service pidp11.boot

```mermaid
sequenceDiagram
    actor A as Automation
    participant HA as homeassistant runtime
    participant I as custom_components.pidp11
    participant RC as SimH remote console :2223
    participant E as SimH pdp11

    A->>HA: call service pidp11.boot boot="211bsd"
    HA->>I: async_call_service
    I->>RC: "AUTH <secret>\n"
    RC-->>I: "OK\n"
    I->>RC: "halt\n"
    RC-->>I: "HALTED\n"
    I->>RC: "boot rl0\n"
    RC->>E: execute
    E-->>RC: boot output...
    RC-->>I: streamed lines
    I->>HA: sensor.pidp11_state -> "running"
    I->>HA: fire event pidp11_boot
```

## 6. Sequence — GPIO switch read -> HA state change (roadmap)

```mermaid
sequenceDiagram
    actor U as User (hat)
    participant G as RP1 GPIO
    participant D as pidp11 GPIO driver
    participant E as SimH pdp11
    participant RC as remote console
    participant I as integration
    participant HA as homeassistant runtime

    U->>G: flip SW_START
    G->>D: input sample
    D->>E: set console register
    D->>RC: async notify SWITCH START=1
    RC-->>I: "EVENT switch start 1\n"
    I->>HA: fire event pidp11_switch pressed=start
    I->>HA: switch.pidp11_start -> on
```

## 7. Install-time view

```mermaid
graph LR
    user([User]) --> haUI[HA UI]
    haUI --> addonStore[Add-on Store]
    haUI --> hacs[HACS]
    addonStore -- "Repositories: paste URL" --> repo[(this repo)]
    hacs -- "Custom repositories: paste URL" --> repo
    repo -- "pidp11-addon/" --> addonStore
    repo -- "custom_components/pidp11/" --> hacs
```
