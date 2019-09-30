import numpy as np
from flare.gp import GaussianProcess
from flare.env import AtomicEnvironment


class EnergyGP(GaussianProcess):
    def __init__(self, kernel, energy_force_kernel, energy_kernel, kernel_grad,
                 hyps, cutoffs, hyp_labels=None, opt_algorithm='L-BFGS-B',
                 maxiter=10, par=False, output=None):

        GaussianProcess.__init__(self, kernel, kernel_grad, hyps, cutoffs,
                                 hyp_labels, energy_force_kernel,
                                 energy_kernel, opt_algorithm, maxiter,
                                 par, output)

        self.training_strucs = []
        self.training_atoms = []
        self.training_envs = []

    def update_db(self, structure, force_range=[]):
        """Add a structure to the training set."""

        # add structure and environments to training set
        self.training_strucs.append(structure)

        env_list = []
        for atom in range(structure.nat):
            env_curr = \
                AtomicEnvironment(structure, atom, self.cutoffs)
            env_list.append(env_curr)
        self.training_envs.append(env_list)

        # add energy to training labels if available
        if structure.energy is not None:
            self.training_labels_np = \
                np.append(self.training_labels_np,
                          structure.energy)

        # add forces to training set if available
        update_indices = []
        if structure.forces is not None:
            noa = len(structure.positions)
            update_indices = force_range or list(range(noa))

            for atom in update_indices:
                self.training_labels_np = \
                    np.append(self.training_labels_np,
                              structure.forces[atom])

        self.training_atoms.append(update_indices)

    def train(self, output=None, grad_tol=1e-4):
        """Train GP model."""
        pass

    def predict(self, x_t: AtomicEnvironment, d: int):
        """Predict force on atomic environment."""
        pass

    def predict_local_energy(self, x_t: AtomicEnvironment):
        """Predict local energy of atomic environment."""
        pass

    def get_kernel_vector(self, test_env: AtomicEnvironment, d_1: int):
        """Get kernel vector between a force component and the training set."""

        kernel_vector = np.zeros(len(self.training_labels_np))
        index = 0

        for struc_no, structure in enumerate(self.training_strucs):
            if structure.energy is not None:
                en_kern = 0
                for train_env in self.training_envs[struc_no]:
                    en_kern += \
                        self.energy_force_kernel(test_env, train_env, d_1,
                                                 self.hyps, self.cutoffs)
                kernel_vector[index] = en_kern
                index += 1

            if structure.forces is not None:
                for atom in self.training_atoms[struc_no]:
                    train_env = self.training_envs[struc_no][atom]
                    for d_2 in range(3):
                        kernel_vector[index] = \
                            self.kernel(test_env, train_env, d_1, d_2 + 1,
                                        self.hyps, self.cutoffs)
                        index += 1

        return kernel_vector

    def en_kern_vec(self, test_env: AtomicEnvironment):
        """Get kernel vector between a local energy and the training set."""
        kernel_vector = np.zeros(len(self.training_labels_np))
        index = 0

        for struc_no, structure in enumerate(self.training_strucs):
            if structure.energy is not None:
                en_kern = 0
                for train_env in self.training_envs[struc_no]:
                    en_kern += \
                        self.energy_kernel(test_env, train_env, self.hyps,
                                           self.cutoffs)
                kernel_vector[index] = en_kern
                index += 1

            if structure.forces is not None:
                for atom in self.training_atoms[struc_no]:
                    train_env = self.training_envs[struc_no][atom]
                    for d_2 in range(3):
                        kernel_vector[index] = \
                            self.energy_force_kernel(train_env, test_env,
                                                     d_2 + 1, self.hyps,
                                                     self.cutoffs)
                        index += 1

        return kernel_vector

    def set_L_alpha(self):
        """Set L matrix and alpha vector based on the current training set."""
        pass