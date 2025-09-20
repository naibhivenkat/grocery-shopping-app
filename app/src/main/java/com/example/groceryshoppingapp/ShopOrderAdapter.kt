package com.example.groceryshoppingapp

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.databinding.ItemShopOrderBinding
import com.example.groceryshoppingapp.models.Order

class ShopOrderAdapter(
    private var orders: List<Order>,
    private val onStatusChange: (String, String) -> Unit
) : RecyclerView.Adapter<ShopOrderAdapter.OrderViewHolder>() {

    class OrderViewHolder(val binding: ItemShopOrderBinding) : RecyclerView.ViewHolder(binding.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): OrderViewHolder {
        val binding = ItemShopOrderBinding.inflate(LayoutInflater.from(parent.context), parent, false)
        return OrderViewHolder(binding)
    }

    override fun getItemCount(): Int = orders.size

    override fun onBindViewHolder(holder: OrderViewHolder, position: Int) {
        val order = orders[position]
        val b = holder.binding

        b.customerName.text = "Customer: ${order.customer}"
        b.orderDetails.text = "Items: ${order.items.joinToString { "${it.name} x${it.quantity}" }}"
        b.currentStatus.text = "Status: ${order.status}"

        b.statusSpinner.setSelection(0)
        b.updateStatusBtn.setOnClickListener {
            val newStatus = b.statusSpinner.selectedItem.toString()
            onStatusChange(order.orderUuid, newStatus)
        }
    }

    fun updateOrders(newOrders: List<Order>) {
        orders = newOrders
        notifyDataSetChanged()
    }
}
