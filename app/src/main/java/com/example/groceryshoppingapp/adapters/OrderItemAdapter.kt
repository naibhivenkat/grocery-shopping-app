package com.example.groceryshoppingapp.adapters

import android.graphics.Color
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.models.ItemQuantity

class OrderItemAdapter(
    private val items: MutableList<ItemQuantity>,
    private val isEditable: Boolean
) : RecyclerView.Adapter<OrderItemAdapter.ItemViewHolder>() {

    init {
        // ✅ Initialize originalQuantity from quantity if not set
        items.forEach {
            if (it.originalQuantity == 0.0) {
                it.originalQuantity = it.quantity
            }
        }
    }

    inner class ItemViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val tvItemName: TextView = view.findViewById(R.id.tv_item_name)
        val tvItemQty: TextView = view.findViewById(R.id.tv_item_quantity)
        val tvItemPrice: TextView = view.findViewById(R.id.tv_item_price)
        val tvItemComment: TextView = view.findViewById(R.id.tv_item_comment)

        val etItemQty: EditText = view.findViewById(R.id.et_item_quantity)
        // ✅ NEW
        val tvOrderedLabel: TextView = view.findViewById(R.id.tv_ordered_qty_label)
        val etItemPrice: EditText = view.findViewById(R.id.et_item_price)
        val etComment: EditText = view.findViewById(R.id.et_item_comment)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ItemViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_order_item, parent, false)
        return ItemViewHolder(view)
    }

    override fun onBindViewHolder(holder: ItemViewHolder, position: Int) {
        val item = items[position]
        holder.tvItemName.text = item.name

        // 🟩 READ-ONLY VIEW (Customer)
        if (!isEditable) {
            holder.etItemQty.visibility = View.GONE
            holder.etItemPrice.visibility = View.GONE
            holder.etComment.visibility = View.GONE
            holder.tvOrderedLabel.visibility = View.GONE

            holder.tvItemQty.visibility = View.VISIBLE
            holder.tvItemPrice.visibility = View.VISIBLE
            holder.tvItemComment.visibility = if (!item.comment.isNullOrBlank()) View.VISIBLE else View.GONE

            // Show if it was a partial delivery
            if (item.originalQuantity > item.quantity) {
                holder.tvItemQty.text = "Delivered: ${item.quantity} (Ord: ${item.originalQuantity})"
                holder.tvItemQty.setTextColor(Color.RED)
            } else {
                holder.tvItemQty.text = "Qty: ${item.quantity}"
                holder.tvItemQty.setTextColor(Color.BLACK)
            }
            holder.tvItemPrice.text = "₹ %.2f".format(item.price)
            holder.tvItemComment.text = "Comment: ${item.comment}"
        }

        // 🟦 EDITABLE VIEW (Shopkeeper)
        else {
            holder.tvItemQty.visibility = View.GONE
            holder.tvItemPrice.visibility = View.GONE
            holder.tvItemComment.visibility = View.GONE

            holder.etItemQty.visibility = View.VISIBLE
            holder.etItemPrice.visibility = View.VISIBLE
            holder.etComment.visibility = View.VISIBLE

            // ✅ Show original ordered qty
            holder.tvOrderedLabel.visibility = View.VISIBLE
            holder.tvOrderedLabel.text = "/ Ordered: ${item.originalQuantity}"

            holder.etItemQty.setText(item.quantity.toString())
            holder.etItemPrice.setText(item.price.toString())
            holder.etComment.setText(item.comment ?: "")

            holder.etItemQty.addTextChangedListener(object : TextWatcher {
                override fun afterTextChanged(s: Editable?) {
                    val newQty = s?.toString()?.toDoubleOrNull()
                    if (newQty != null && newQty >= 0) {
                        // Optional: Warn if > original
                        if(newQty > item.originalQuantity) {
                            holder.etItemQty.error = "Max: ${item.originalQuantity}"
                        } else {
                            item.quantity = newQty
                        }
                    }
                }
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            })

            // ... (Price and Comment TextWatchers same as before)
            holder.etItemPrice.addTextChangedListener(object : TextWatcher {
                override fun afterTextChanged(s: Editable?) {
                    val newPrice = s?.toString()?.toDoubleOrNull()
                    if (newPrice != null && newPrice >= 0.0) item.price = newPrice
                }
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            })

            holder.etComment.addTextChangedListener(object : TextWatcher {
                override fun afterTextChanged(s: Editable?) {
                    item.comment = s?.toString()
                }
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            })
        }
    }

    override fun getItemCount(): Int = items.size

    fun getUpdatedItems(): List<ItemQuantity> = items
}