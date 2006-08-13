# Zeobuilder is an extensible GUI-toolkit for molecular model construction.
# Copyright (C) 2005 Toon Verstraelen
#
# This file is part of Zeobuilder.
#
# Zeobuilder is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
# --


from zeobuilder import context
from zeobuilder.actions.composed import Immediate
from zeobuilder.actions.abstract import CenterAlignBase
from zeobuilder.actions.collections.menu import MenuInfo
from zeobuilder.nodes.parent_mixin import ContainerMixin
from zeobuilder.nodes.glcontainermixin import GLContainerMixin
from zeobuilder.gui.simple import ok_information
import zeobuilder.actions.primitive as primitive

from molmod.data import periodic, bonds, BOND_SINGLE, BOND_DOUBLE, BOND_TRIPLE
from molmod.transformations import Translation, Complete, Rotation

import numpy

import math


class ChemicalFormula(Immediate):
    description = "Show chemical formula"
    menu_info = MenuInfo("default/_Object:tools/_Molecular:info", "_Chemical Formula", order=(0, 4, 1, 5, 2, 0))

    def analyze_selection():
        if not Immediate.analyze_selection(): return False
        if len(context.application.cache.nodes) == 0: return False
        return True
    analyze_selection = staticmethod(analyze_selection)

    def do(self):
        atom_counts = {}
        Atom = context.application.plugins.get_node("Atom")

        def recursive_chem_counter(node):
            if isinstance(node, Atom):
                if node.number not in atom_counts:
                    atom_counts[node.number] = 1
                else:
                    atom_counts[node.number] += 1
            if isinstance(node, ContainerMixin):
                for child in node.children:
                    recursive_chem_counter(child)

        for node in context.application.cache.nodes:
            recursive_chem_counter(node)

        total = 0
        if len(atom_counts) > 0:
            answer = "Chemical formula: "
            for atom_number, count in atom_counts.iteritems():
                answer += "%s<sub>%i</sub>" % (periodic[atom_number].symbol, count)
                total += count
            answer += "\n\nNumber of atoms: %i" % total
        else:
            answer = "No atoms found."
        ok_information(answer)


def yield_particles(node, parent=None):
    if parent is None:
        parent = node
    Atom = context.application.plugins.get_node("Atom")
    for child in node.children:
        if isinstance(child, Atom):
            yield (
                periodic[child.number].mass,
                child.get_frame_relative_to(parent).t
            )
        elif isinstance(child, GLContainerMixin):
            for particle in yield_particles(child, parent):
                yield particle

def calculate_center_of_mass(particles):
    weighted_center = numpy.zeros(3, float)
    total_mass = 0.0
    for mass, coordinate in particles:
        weighted_center += mass*coordinate
        total_mass += mass
    if total_mass == 0.0:
        return total_mass, weighted_center
    else:
        return total_mass, weighted_center/total_mass

def calculate_inertia_tensor(particles, center):
    tensor = numpy.zeros((3,3), float)
    for mass, coordinate in particles:
        delta = coordinate - center
        tensor += mass*(
            numpy.dot(delta, delta)*numpy.identity(3, float)
           -numpy.outer(delta, delta)
        )
    return tensor

def default_rotation_matrix(inertia_tensor):
    if abs(inertia_tensor.ravel()).max() < 1e-6:
        return numpy.identity(3, float)
    evals, evecs = numpy.linalg.eig(inertia_tensor)
    result = numpy.array([evecs[:,index] for index in evals.argsort()], float).transpose()
    if numpy.linalg.det(result) < 0: result *= -1
    return result


class CenterOfMass(CenterAlignBase):
    description = "Center of mass"
    menu_info = MenuInfo("default/_Object:tools/_Transform:center", "Center of _mass frame", order=(0, 4, 1, 2, 2, 2))

    def analyze_selection():
        # A) calling ancestor
        if not CenterAlignBase.analyze_selection(): return False
        # B) validating
        cache = context.application.cache
        if not isinstance(cache.node, ContainerMixin): return False
        if len(cache.translated_children) == 0: return False
        if cache.some_children_fixed: return False
        # C) passed all tests:
        return True
    analyze_selection = staticmethod(analyze_selection)

    def do(self):
        cache = context.application.cache
        node = cache.node
        translation = Translation()
        mass, com = calculate_center_of_mass(yield_particles(node))
        if mass == 0.0:
            raise UserError("No particles (atoms) found.")
        translation.t = com
        CenterAlignBase.do(self, node, cache.translated_children, translation)


class CenterOfMassAndPrincipalAxes(CenterOfMass):
    description = "Center of mass and principal axes"
    menu_info = MenuInfo("default/_Object:tools/_Transform:centeralign", "Center of mass and _principal axes frame", order=(0, 4, 1, 2, 4, 1))

    def analyze_selection():
        # A) calling ancestor
        if not CenterOfMass.analyze_selection(): return False
        # B) validating
        cache = context.application.cache
        if not isinstance(cache.node, ContainerMixin): return False
        if len(cache.transformed_children) == 0: return False
        if cache.some_children_fixed: return False
        # C) passed all tests:
        return True
    analyze_selection = staticmethod(analyze_selection)

    def do(self):
        cache = context.application.cache
        node = cache.node
        transformation = Complete()

        mass, com = calculate_center_of_mass(yield_particles(node))
        if mass == 0.0:
            raise UserError("No particles (atoms) found.")
        transformation.t = com

        tensor = calculate_inertia_tensor(yield_particles(node), com)
        transformation.r = default_rotation_matrix(tensor)
        CenterAlignBase.do(self, node, cache.translated_children, transformation)


class SaturateWithHydrogens(Immediate):
    description = "Saturate with hydrogens"
    menu_info = MenuInfo("default/_Object:tools/_Molecular:add", "S_aturate with hydrogens", order=(0, 4, 1, 5, 1, 2))
    opening_angles = {
        # (hybr, numsit): angle
          (2,    1):                  0.0,
          (3,    1):                  0.0,
          (4,    1):                  0.0,
          (3,    2):      math.pi/180*60.0,
          (4,    2):      math.pi/180*54.735610317245346,
          (4,    3):      math.pi/180*70.528779365509308
    }

    def analyze_selection():
        # A) calling ancestor
        if not Immediate.analyze_selection(): return False
        # B) validating
        if len(context.application.cache.nodes) == 0: return False
        # C) passed all tests:
        return True
    analyze_selection = staticmethod(analyze_selection)

    def do(self):
        Atom = context.application.plugins.get_node("Atom")
        Bond = context.application.plugins.get_node("Bond")

        def lone_pairs(number):
            # very naive implemention for neutral atoms in the second and the
            # third row
            if number <= 6:
                return 0
            elif number <= 10:
                return number - 6
            elif number <= 14:
                return 0
            elif number <= 18:
                return number - 14
            else:
                return 0

        def valence_el(number):
            # very naive implemention for neutral atoms in the second and the
            # third row
            if number <= 2:
                return number
            elif number <= 10:
                return number - 2
            elif number <= 18:
                return number - 10
            else:
                return 0

        def add_hydrogens(atom):
            existing_bonds = list(atom.yield_bonds())
            num_bonds = len(existing_bonds)
            if num_bonds == 0:
                return

            used_valence = 0
            oposite_direction = numpy.zeros(3, float)
            for bond in existing_bonds:
                shortest_vector = bond.shortest_vector_relative_to(atom.parent)
                if bond.children[1].target == atom:
                    shortest_vector *= -1
                oposite_direction -= shortest_vector

                if bond.bond_type == BOND_SINGLE:
                    used_valence += 1
                elif bond.bond_type == BOND_DOUBLE:
                    used_valence += 2
                elif bond.bond_type == BOND_TRIPLE:
                    used_valence += 3

            oposite_direction /= numpy.linalg.norm(oposite_direction)

            num_hydrogens = valence_el(atom.number) - 2*lone_pairs(atom.number) - used_valence
            if num_hydrogens <= 0:
                return

            hybride_count = num_hydrogens + lone_pairs(atom.number) + num_bonds - (used_valence - num_bonds)
            num_sites = num_hydrogens + lone_pairs(atom.number)
            rotation = Rotation()
            rotation.set_rotation_properties(2*math.pi / float(num_sites), oposite_direction, False)
            opening_key = (hybride_count, num_sites)
            opening_angle = self.opening_angles.get(opening_key)
            if opening_angle is None:
                return

            if num_bonds == 1:
                first_bond = existing_bonds[0]
                other_atom = first_bond.children[0].target
                if other_atom == atom:
                    other_atom = first_bond.children[1].target
                other_bonds = [bond for bond in other_atom.yield_bonds() if bond != first_bond]
                if len(other_bonds) > 0:
                    normal = other_bonds[0].shortest_vector_relative_to(atom.parent)
                    normal -= numpy.dot(normal, oposite_direction) * oposite_direction
                    normal /= numpy.linalg.norm(normal)
                    if other_bonds[0].children[0].target == other_atom:
                        normal *= -1
                else:
                    normal = random_orthonormal(oposite_direction)
            elif num_bonds == 2:
                normal = numpy.cross(oposite_direction, existing_bonds[0].shortest_vector_relative_to(atom.parent))
                normal /= numpy.linalg.norm(normal)
            elif num_bonds == 3:
                normal = random_orthonormal(oposite_direction)
            else:
                return

            bond_length = bonds.get_length(atom.number, 1, BOND_SINGLE)
            h_pos = bond_length*(oposite_direction*math.cos(opening_angle) + normal*math.sin(opening_angle))

            for i in range(num_hydrogens):
                H = Atom(name="auto H", number=1)
                H.transformation.t = atom.transformation.t + h_pos
                primitive.Add(H, atom.parent)
                bond = Bond(name="aut H bond", targets=[atom, H])
                primitive.Add(bond, atom.parent)
                h_pos = rotation.vector_apply(h_pos)

        def hydrogenate_unsaturated_atoms(nodes):
            for node in nodes:
                if isinstance(node, Atom):
                    add_hydrogens(node)
                elif isinstance(node, ContainerMixin):
                    hydrogenate_unsaturated_atoms(node.children)

        hydrogenate_unsaturated_atoms(context.application.cache.nodes)



actions = {
    "ChemicalFormula": ChemicalFormula,
    "CenterOfMass": CenterOfMass,
    "CenterOfMassAndPrincipalAxes": CenterOfMassAndPrincipalAxes,
    "SaturateWithHydrogens": SaturateWithHydrogens,
}