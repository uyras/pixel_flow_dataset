# Pixel Flow

English | [Русский](README_RU.md)

## Base case

[base_case](base_case/) models steady, two-dimensional incompressible laminar flow through a channel using OpenFOAM Foundation 14. A square region inside the channel is divided into an `L` × `L` grid; `solid_mask` determines which squares are solid and which contain fluid. The inlet has a parabolic velocity profile whose maximum is `U_in`.

Edit [parameters.json](base_case/parameters.json) to set the geometry, flow properties, mesh resolution, and convergence limits. The case generator uses these parameters to write the mesh and solver dictionaries, initial fields, and a geometry preview. To run the case, activate OpenFOAM Foundation 14 and execute:

```bash
cd base_case
./Allrun
```

`Allrun` regenerates the case files, builds and checks the mesh, runs the solver, and checks convergence. Logs and `run_status.json` record the outcome. See the [base case documentation](base_case/README_RU.md) for details.

To clean a case before a fresh run, execute `./Allclean` from its directory. It removes `constant/polyMesh`, nonzero time directories, `run_status.json`, and the `log.blockMesh`, `log.checkMesh`, and `log.foamRun` logs. Initial fields in `0`, parameters, and scripts are retained. Save any results you need before cleaning.

`Allclean` cleans its own case by default. To select another case, use `./Allclean --case /path/to/case`. The target must contain `case_summary.json`; otherwise, cleaning is refused.

## OpenFOAM case generator

The dataset generator creates parameterized OpenFOAM Foundation 14 cases from [base_case](base_case/). It combines each configured grid size `L` and inlet speed `U_in` with predefined and random solid masks. A mask value of `1` represents solid; `0` represents fluid. Its first row is the bottom row.

Edit [dataset_settings.json](dataset_settings.json) to set:

- `L`: grid sizes for the square solid mask.
- `U_in`: inlet speeds.
- `random_count`: number of unique random masks per `L`, in addition to the predefined masks.
- `seed`: random seed for reproducible generation.
- `output`: output directory, relative to the settings file.

The predefined masks include empty and full masks, each diagonal and both diagonals, and their inverses. Empty and full cases are generated only for the first `L` and their names omit `L`; the manifest records the size used. Other case parameters come from [base_case/parameters.json](base_case/parameters.json).

Run from the project root with Python 3.9 or newer:

```bash
python3 generate_dataset.py
```

The output directory must not already exist. Each generated case includes its parameters, OpenFOAM dictionaries, and an `Allrun` script. The output also contains `manifest.csv` and `dataset_info.json`. Generation does not run the calculations.

Activate OpenFOAM Foundation 14 and run `./Allrun` from the project root to execute every immediate case subdirectory sequentially. Pass a different directory as `./Allrun /path/to/cases`. Relative paths on the command line are resolved from the current directory; `output` in the settings is relative to the settings file. The script continues after failures and returns a nonzero exit status if any launch fails.

Cases whose `run_status.json` has both `converged` and `only_one_result_time` set to `true` are skipped in both modes. Missing status or a negative result triggers a launch; an invalid status is reported as an error. A failed or incomplete case may still contain a mesh or results, in which case its own `Allrun` refuses to overwrite them: inspect the results and use that case's `Allclean` before rerunning if appropriate.

To submit one Slurm job per case, set `slurm.enabled` to `true` in [dataset_settings.json](dataset_settings.json), or run `./Allrun --mode slurm`. Use `--mode local` to override the setting for a local run. The Slurm group also accepts `partition`, `account`, `time` and `memory` (passed as `--partition`, `--account`, `--time` and `--mem`); an empty string omits the option. Adjust these values to your cluster. Each job requests one task and one CPU, runs from its case directory, and writes `slurm-<jobid>.out` and `slurm-<jobid>.err` there. The submission environment must provide OpenFOAM on the compute nodes. A successful submission only means Slurm accepted the job; check the job queue and logs for the calculation result.

Use `--config`, `--output`, `--random-count`, or `--seed` to select another settings file or override individual settings. See [the base case documentation](base_case/README_RU.md) for details of the simulation.

To clean every case in the configured output directory, run `./Allclean` from the project root. You can instead specify a directory with `./Allclean /path/to/cases`. The script runs `Allclean` in each immediate subdirectory, continues after errors, and exits with a nonzero status if any case could not be cleaned.
# Case status

Run `python3 case_status.py` for a quick summary, or pass a case directory as an argument. Add `--details` to list individual cases. A case is complete when both `converged` and `only_one_result_time` in `run_status.json` are true, matching `Allrun`. Without a final status, the script reports the latest available log or the absence of logs; a log does not prove that a process is running. Errors are checked only at the end of the latest log. The script does not query Slurm or modify cases.

## Collecting results

Activate an environment with NumPy and OpenFOAM Foundation 14, then run `python3 collect_dataset.py --output results.npz` to create a compressed NPZ dataset. Run the same command with `--append` to add newly completed cases from the same source directory without changing existing entries. Append loads the arrays into memory, rewrites the archive to a temporary file and replaces it. Pass a case directory as the first argument; the default is `output` in `dataset_settings.json`. A case is complete when both status flags `converged` and `only_one_result_time` are true. Errors in completed cases are reported and cause a nonzero exit code, while other cases are still processed. OpenFOAM fields must be ASCII. `foamPostProcess` calculates cell centres in a temporary copy of each case.

Load the file with `numpy.load(..., allow_pickle=False)`. The `metadata` uint8 array contains UTF-8 JSON, with a `cases` list holding each case's `name`, array prefix `key`, mesh reference `mesh`, final `time` and peak inlet speed `U_in`. Arrays `<key>/p`, `<key>/U`, `<key>/inlet_U` and the array named by `mesh` contain pressure, cell velocity, inlet face velocity and cell centres, respectively. Their shapes are `(cell_count,)`, `(cell_count, 3)`, `(inlet_count, 3)` and `(cell_count, 3)`; all are float64 in OpenFOAM order. Identical arrays of cell centres are shared. See the Russian README for a NumPy reading example.
