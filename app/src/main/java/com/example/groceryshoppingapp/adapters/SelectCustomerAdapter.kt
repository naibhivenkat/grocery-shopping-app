package com.example.groceryshoppingapp.adapters

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.databinding.ItemSelectCustomerBinding
import com.example.groceryshoppingapp.models.AppUser

class SelectCustomerAdapter(
    private val items: List<AppUser>,
    private val click: (AppUser) -> Unit
) : RecyclerView.Adapter<SelectCustomerAdapter.VH>() {

    inner class VH(val binding: ItemSelectCustomerBinding)
        : RecyclerView.ViewHolder(binding.root) {

        fun bind(u: AppUser) {
            binding.tvName.text = u.fullName
            binding.tvPhone.text = if (u.phone.isNotEmpty()) "Phone: ${u.phone}" else "Phone: -"
            binding.root.setOnClickListener { click(u) }
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        return VH(
            ItemSelectCustomerBinding.inflate(
                LayoutInflater.from(parent.context),
                parent,
                false
            )
        )
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        holder.bind(items[position])
    }

    override fun getItemCount() = items.size
}
