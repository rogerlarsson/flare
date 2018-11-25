import sys
import numpy as np
import datetime
import time
from typing import List
from struc import Structure
from gp import GaussianProcess
from env import ChemicalEnvironment
from qe_util import run_espresso, parse_qe_input, \
    qe_input_to_structure, parse_qe_forces


class OTF(object):
    def __init__(self, qe_input: str, dt: float, number_of_steps: int,
                 kernel: str, bodies: int, cutoff: float, pw_loc: str,
                 std_tolerance_factor: float = 1, opt_algo: str='BFGS',
                 prev_pos_init: List[np.ndarray] = None):

        self.qe_input = qe_input
        self.dt = dt
        self.Nsteps = number_of_steps
        self.gp = GaussianProcess(kernel, bodies, opt_algorithm=opt_algo)
        self.cutoff = cutoff
        self.std_tolerance = std_tolerance_factor
        self.pw_loc = pw_loc

        positions, species, cell, masses = parse_qe_input(self.qe_input)
        self.structure = Structure(lattice=cell, species=species,
                                   positions=positions, cutoff=cutoff,
                                   mass_dict=masses,
                                   prev_positions=prev_pos_init)

        self.curr_step = 0
        self.train_structure = None
        self.write_header()

    def run(self):
        self.start_time = time.time()

        if self.std_tolerance != 0:
            self.run_and_train()
            self.write_md_config()

        while self.curr_step < self.Nsteps:

            self.predict_on_structure()

            std_in_bound, target_atom = self.is_std_in_bound()
            if not std_in_bound:
                self.write_md_config()
                self.run_and_train(target_atom)

            self.write_md_config()
            self.update_positions()

        self.conclude_run()

    def predict_on_structure(self):
        for n in range(self.structure.nat):
            chemenv = ChemicalEnvironment(self.structure, n)
            for i in range(3):
                force, var = self.gp.predict(chemenv, i + 1)
                self.structure.forces[n][i] = float(force)
                self.structure.stds[n][i] = np.sqrt(np.absolute(var))

        self.structure.dft_forces = False

    def run_and_train(self, target_atom: int = None):
        self.write_to_output('=' * 20 + '\n')

        if self.train_structure is None:
            self.write_to_output('Calling Quantum Espresso...')
        else:
            self.write_to_output('Calling DFT due to atom {} at position {} '
                                 'with uncertainties {}...'
                                 .format(target_atom,
                                         self.structure.positions[target_atom],
                                         self.structure.stds[target_atom]))

        self.train_structure = self.structure
        train_atoms = list(range(self.train_structure.nat))
        forces = run_espresso(self.qe_input, self.train_structure,
                              self.pw_loc)
        self.train_structure.forces = forces

        self.structure.dft_forces = True
        self.structure.forces = [np.array(force) for force in forces]
        self.structure.stds = [np.zeros(3) for n in range(self.structure.nat)]
        self.write_to_output('Done.\n')
        self.write_last_dft_run()

        self.write_to_output('Updating database hyperparameters...\n')
        self.gp.update_db(self.train_structure, forces,
                          custom_range=train_atoms)
        self.gp.train()
        self.write_hyps()

    def update_positions(self):
        dtdt = self.dt ** 2

        for i, pre_pos in enumerate(self.structure.prev_positions):
            temp_pos = np.copy(self.structure.positions[i])
            mass = self.structure.mass_dict[self.structure.species[i]]
            pos = self.structure.positions[i]
            forces = self.structure.forces[i]

            self.structure.positions[i] = \
                2 * pos - pre_pos + dtdt * forces / mass

            self.structure.prev_positions[i] = np.copy(temp_pos)

        self.curr_step += 1

    @staticmethod
    def write_to_output(string: str, output_file: str = 'otf_run.out'):
        with open(output_file, 'a') as f:
            f.write(string)

    def write_header(self):
        with open('otf_run.out', 'w') as f:
            f.write(str(datetime.datetime.now()) + '\n')

        headerstring = ''
        headerstring += 'Structure Cutoff Radius: {}\n'.format(
            self.structure.cutoff)
        headerstring += 'Kernel: {}\n'.format(
            self.gp.kernel_name)
        headerstring += '# Hyperparameters: {}\n'.format(
            len(self.gp.hyps))
        headerstring += 'Initial Hyperparameter Optimization Algorithm: {}' \
                        '\n'.format(self.gp.algo)
        headerstring += 'Timestep (ps): {}\n'.format(self.dt)
        headerstring += 'Number of Frames: {}\n'.format(self.Nsteps)
        headerstring += 'Number of Atoms: {}\n'.format(self.structure.nat)
        headerstring += 'System Species: {}\n'.format(set(
            self.structure.species))

        self.write_to_output(headerstring)

    def write_md_config(self):
        string = "-------------------- \n"

        # Mark if a frame had DFT forces with an asterisk
        string += "-" + ('*' if self.structure.dft_forces else ' ') + \
                  "Frame: " + str(self.curr_step)

        string += " Simulation Time: "
        string += str(np.round(self.dt * self.curr_step, 6)) + '\n'

        # Construct Header line
        string += 'El \t\t\t  Position (A) \t\t\t\t\t '
        if not self.structure.dft_forces:
            string += 'GP Force (ev/A) '
        else:
            string += 'DFT Force (ev/A) '
        string += '\t\t\t\t\t\t Std. Dev (ev/A) \n'

        # Construct atom-by-atom description
        for i in range(len(self.structure.positions)):
            string += self.structure.species[i] + ' '
            for j in range(3):
                string += str("%.8f" % self.structure.positions[i][j]) + ' '
            string += '\t'
            for j in range(3):
                string += str("%.8f" % self.structure.forces[i][j]) + ' '
            string += '\t'
            for j in range(3):
                string += str('%.6e' % self.structure.stds[i][j]) + ' '
            string += '\n'

        self.write_to_output(string)

    def write_last_dft_run(self):
        qe_strings = 'El \t\t\t  Position (A) \t\t\t\t\t DFT Force (ev/A) \n'

        for n in range(self.train_structure.nat):
            qe_strings += self.train_structure.species[n] + ': '
            for i in range(3):
                qe_strings += '%.8f  ' % self.train_structure.positions[n][i]
            qe_strings += '\t '
            for i in range(3):
                qe_strings += '%.8f  ' % self.train_structure.forces[n][i]
            qe_strings += '\n'

        self.write_to_output(qe_strings)
        self.write_to_output('=' * 20 + '\n')

    def write_hyps(self):
        self.write_to_output('New GP Hyperparameters: \n')

        for i, label in enumerate(self.gp.hyp_labels):
            self.write_to_output('Hyp{} : {} = {}\n'
                                 .format(i, label, self.gp.hyps[i]))

    def conclude_run(self):
        footer = '▬' * 20 + '\n'
        footer += 'Run complete. \n'

        self.write_to_output(footer)

    def is_std_in_bound(self) -> (bool, int):
        stds = self.structure.stds
        max_std = np.nanmax(stds)

        # negative tolerance is a hard user-defined std cutoff
        # positive is a multiple of the noise std
        # 0 means no failure condition (DFT is off)
        tol = self.std_tolerance

        if tol == 0:
            return True, -1
        constant_cutoff_trip = tol < 0 and max_std >= np.abs(tol)
        rel_cutoff_trip = tol > 0 and max_std >= tol * np.abs(self.gp.hyps[-1])

        if constant_cutoff_trip or rel_cutoff_trip:
            nat = self.structure.nat
            target_atom = np.argmax([np.max(stds[i]) for i in range(nat)])
            return False, target_atom
        else:
            return True, -1
